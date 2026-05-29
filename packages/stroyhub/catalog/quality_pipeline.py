from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stroyhub.catalog.attributes import (
    ExtractedAttribute,
    ProductAttributeExtraction,
    extract_product_attributes,
)
from stroyhub.catalog.categorization import CategoryDecision, CategoryPrediction
from stroyhub.catalog.normalization_decisions import NormalizationDecision, decide_normalization
from stroyhub.catalog.product_match_generation import (
    ProductMatchCandidateGenerator,
    ProductMatchGenerationFilters,
)
from stroyhub.catalog.source_category_mappings import categorizer_for_session
from stroyhub.db.repositories import CategoryRepository, CategoryUpsert
from stroyhub.models import CanonicalProduct, CategoryOverride, ProductMatch, SourceProduct
from stroyhub.parsers.common import JsonObject

_PIPELINE_VERSION = "catalog_quality_pipeline_v1"


@dataclass(frozen=True, kw_only=True)
class CatalogQualityPipelineResult:
    shop_id: int
    products_seen: int
    products_processed: int
    products_failed: int
    candidates_seen: int
    candidates_created: int
    candidates_skipped_existing: int

    def as_raw(self) -> JsonObject:
        return {
            "shop_id": self.shop_id,
            "products_seen": self.products_seen,
            "products_processed": self.products_processed,
            "products_failed": self.products_failed,
            "candidates_seen": self.candidates_seen,
            "candidates_created": self.candidates_created,
            "candidates_skipped_existing": self.candidates_skipped_existing,
        }


class CatalogQualityPipeline:
    def __init__(self, session: Session) -> None:
        self._session = session

    def run_for_shop(
        self,
        shop_id: int,
        *,
        processed_at: datetime | None = None,
        generate_candidates: bool = True,
    ) -> CatalogQualityPipelineResult:
        return self._run_for_products(
            shop_id=shop_id,
            products=self._source_products(shop_id),
            processed_at=processed_at,
            generate_candidates=generate_candidates,
        )

    def run_for_product(
        self,
        source_product_id: int,
        *,
        processed_at: datetime | None = None,
    ) -> CatalogQualityPipelineResult:
        product = self._source_product(source_product_id)
        if product is None:
            return CatalogQualityPipelineResult(
                shop_id=0,
                products_seen=0,
                products_processed=0,
                products_failed=0,
                candidates_seen=0,
                candidates_created=0,
                candidates_skipped_existing=0,
            )
        return self._run_for_products(
            shop_id=product.shop_id,
            products=[product],
            processed_at=processed_at,
            generate_candidates=False,
        )

    def _run_for_products(
        self,
        *,
        shop_id: int,
        products: list[SourceProduct],
        processed_at: datetime | None,
        generate_candidates: bool,
    ) -> CatalogQualityPipelineResult:
        now = processed_at or datetime.now(UTC)
        categorizer = categorizer_for_session(self._session)
        category_repository = CategoryRepository(self._session)
        stage_data: dict[int, tuple[ProductAttributeExtraction, CategoryDecision]] = {}
        products_processed = 0
        products_failed = 0

        for product in products:
            try:
                attributes = extract_product_attributes(
                    product.title,
                    source=product.source,
                    category_raw=product.category_raw,
                )
            except Exception as exc:
                product.raw = _with_pipeline_failure(
                    product.raw,
                    processed_at=now,
                    failed_stage="attributes",
                    error=str(exc),
                )
                products_failed += 1
                continue

            try:
                category_decision = categorizer.decide(
                    title=product.title,
                    source=product.source,
                    category_raw=product.category_raw,
                    description=product.description,
                )
                if category_decision.prediction is not None:
                    category_id = _category_id_for_prediction(
                        category_repository,
                        category_decision.prediction,
                    )
                    if not _has_active_category_override(self._session, product.id):
                        product.category_id = category_id

                stage_data[product.id] = (attributes, category_decision)
            except Exception as exc:
                product.raw = _with_pipeline_failure(
                    product.raw,
                    processed_at=now,
                    failed_stage="categorization",
                    error=str(exc),
                )
                products_failed += 1

        self._session.flush()
        candidates_seen = 0
        candidates_created = 0
        candidates_skipped_existing = 0
        if generate_candidates:
            candidate_result = ProductMatchCandidateGenerator(self._session).generate(
                ProductMatchGenerationFilters(shop_id=shop_id, limit=1000)
            )
            candidates_seen = candidate_result.candidates_seen
            candidates_created = candidate_result.candidates_created
            candidates_skipped_existing = candidate_result.candidates_skipped_existing

        for product in products:
            product_stage_data = stage_data.get(product.id)
            if product_stage_data is None:
                continue
            attributes, category_decision = product_stage_data
            try:
                accepted_match = self._accepted_match(product.id)
                rejected_canonical_product_ids = self._rejected_canonical_product_ids(product.id)
                normalization_decision = decide_normalization(
                    product,
                    candidates=self._canonical_candidates(product),
                    rejected_canonical_product_ids=rejected_canonical_product_ids,
                )
                product.raw = _with_catalog_quality_raw(
                    product.raw,
                    processed_at=now,
                    attributes=attributes.attributes,
                    attribute_confidence=attributes.confidence,
                    attribute_reasons=attributes.reasons,
                    category_decision=category_decision,
                    normalization_decision=normalization_decision,
                    accepted_match=accepted_match,
                    rejected_canonical_product_ids=rejected_canonical_product_ids,
                )
                products_processed += 1
            except Exception as exc:
                product.raw = _with_pipeline_failure(
                    product.raw,
                    processed_at=now,
                    failed_stage="normalization",
                    error=str(exc),
                )
                products_failed += 1

        self._session.flush()
        return CatalogQualityPipelineResult(
            shop_id=shop_id,
            products_seen=len(products),
            products_processed=products_processed,
            products_failed=products_failed,
            candidates_seen=candidates_seen,
            candidates_created=candidates_created,
            candidates_skipped_existing=candidates_skipped_existing,
        )

    def _source_products(self, shop_id: int) -> list[SourceProduct]:
        statement = (
            select(SourceProduct)
            .where(SourceProduct.shop_id == shop_id, SourceProduct.is_active.is_(True))
            .order_by(SourceProduct.id.asc())
        )
        return list(self._session.scalars(statement))

    def _source_product(self, source_product_id: int) -> SourceProduct | None:
        return self._session.get(SourceProduct, source_product_id)

    def _canonical_candidates(self, product: SourceProduct) -> tuple[CanonicalProduct, ...]:
        statement = (
            select(CanonicalProduct)
            .join(ProductMatch, ProductMatch.canonical_product_id == CanonicalProduct.id)
            .where(
                ProductMatch.source_product_id == product.id,
                ProductMatch.status == "candidate",
                CanonicalProduct.match_status == "active",
            )
            .order_by(ProductMatch.confidence.desc(), ProductMatch.id.asc())
        )
        if product.category_id is not None:
            statement = statement.where(CanonicalProduct.category_id == product.category_id)
        return tuple(self._session.scalars(statement))

    def _accepted_match(self, source_product_id: int) -> ProductMatch | None:
        return self._session.scalar(
            select(ProductMatch).where(
                ProductMatch.source_product_id == source_product_id,
                ProductMatch.status == "accepted",
            )
        )

    def _rejected_canonical_product_ids(self, source_product_id: int) -> tuple[int, ...]:
        return tuple(
            self._session.scalars(
                select(ProductMatch.canonical_product_id).where(
                    ProductMatch.source_product_id == source_product_id,
                    ProductMatch.status == "rejected",
                )
            )
        )


def _category_id_for_prediction(
    category_repository: CategoryRepository,
    prediction: CategoryPrediction,
) -> int:
    parent_id = None
    if prediction.parent_slug is not None and prediction.parent_name is not None:
        parent = category_repository.upsert(
            CategoryUpsert(slug=prediction.parent_slug, name=prediction.parent_name)
        )
        parent_id = parent.id

    category = category_repository.upsert(
        CategoryUpsert(
            slug=prediction.category_slug,
            name=prediction.category_name,
            parent_id=parent_id,
        )
    )
    return category.id


def _has_active_category_override(session: Session, source_product_id: int) -> bool:
    return (
        session.scalar(
            select(CategoryOverride.id).where(
                CategoryOverride.source_product_id == source_product_id,
                CategoryOverride.status == "active",
            )
        )
        is not None
    )


def _with_catalog_quality_raw(
    raw: JsonObject | None,
    *,
    processed_at: datetime,
    attributes: tuple[ExtractedAttribute, ...],
    attribute_confidence: Decimal,
    attribute_reasons: tuple[str, ...],
    category_decision: CategoryDecision,
    normalization_decision: NormalizationDecision,
    accepted_match: ProductMatch | None,
    rejected_canonical_product_ids: tuple[int, ...],
) -> JsonObject:
    updated = dict(raw or {})
    updated["catalog_quality"] = {
        "version": _PIPELINE_VERSION,
        "status": "processed",
        "processed_at": processed_at.isoformat(),
        "cleanup": {
            "status": "passed",
            "processed_at": processed_at.isoformat(),
        },
        "attributes": {
            "status": "passed",
            "confidence": str(attribute_confidence),
            "reasons": list(attribute_reasons),
            "items": [_attribute_raw(attribute) for attribute in attributes],
            "processed_at": processed_at.isoformat(),
        },
        "categorization": {
            "status": category_decision.status,
            "confidence": category_decision.confidence,
            "reasons": list(category_decision.reasons),
            "category_slug": (
                category_decision.prediction.category_slug
                if category_decision.prediction is not None
                else None
            ),
            "processed_at": processed_at.isoformat(),
        },
        "normalization": _normalization_raw(
            normalization_decision,
            processed_at=processed_at,
            accepted_match=accepted_match,
            rejected_canonical_product_ids=rejected_canonical_product_ids,
        ),
    }
    return updated


def _normalization_raw(
    decision: NormalizationDecision,
    *,
    processed_at: datetime,
    accepted_match: ProductMatch | None,
    rejected_canonical_product_ids: tuple[int, ...],
) -> JsonObject:
    if accepted_match is not None:
        return {
            "status": "accepted",
            "action": "accepted",
            "confidence": str(accepted_match.confidence),
            "canonical_product_id": accepted_match.canonical_product_id,
            "method": accepted_match.method,
            "processed_at": processed_at.isoformat(),
        }

    raw: JsonObject = {
        "status": decision.status,
        "action": decision.action,
        "confidence": str(decision.confidence),
        "blockers": list(decision.blockers),
        "processed_at": processed_at.isoformat(),
    }
    if decision.canonical_product_id is not None:
        raw["canonical_product_id"] = decision.canonical_product_id
    if decision.canonical_title is not None:
        raw["canonical_title"] = decision.canonical_title
    if rejected_canonical_product_ids:
        raw["rejected_canonical_product_ids"] = list(rejected_canonical_product_ids)
    return raw


def _with_pipeline_failure(
    raw: JsonObject | None,
    *,
    processed_at: datetime,
    failed_stage: str,
    error: str,
) -> JsonObject:
    updated = dict(raw or {})
    stage_raw: JsonObject = {
        "status": "failed",
        "processed_at": processed_at.isoformat(),
        "error": error,
    }
    updated["catalog_quality"] = {
        "version": _PIPELINE_VERSION,
        "status": "failed",
        "processed_at": processed_at.isoformat(),
        "failed_stage": failed_stage,
        "cleanup": {
            "status": "passed",
            "processed_at": processed_at.isoformat(),
        },
        failed_stage: stage_raw,
        "error": error,
    }
    return updated


def _attribute_raw(attribute: ExtractedAttribute) -> dict[str, Any]:
    return {
        "kind": attribute.kind,
        "raw": attribute.raw,
        "values": [str(value) for value in attribute.values],
        "unit": attribute.unit,
        "normalized": attribute.normalized,
        "confidence": str(attribute.confidence),
        "reason": attribute.reason,
    }
