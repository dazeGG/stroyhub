from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from stroyhub.catalog.eligibility import is_matchable_source_product
from stroyhub.db.repositories import ProductMatchCreate, ProductMatchRepository
from stroyhub.ml.matching import (
    ProductMatchCandidate,
    ProductMatchReason,
    generate_product_match_candidates,
)
from stroyhub.models.tables import CanonicalProduct, ProductMatch, SourceProduct
from stroyhub.parsers.common import JsonObject


@dataclass(frozen=True, kw_only=True)
class ProductMatchGenerationFilters:
    source: str | None = None
    shop_id: int | None = None
    category_id: int | None = None
    min_confidence: float = 0.75
    limit: int = 100


@dataclass(frozen=True, kw_only=True)
class ProductMatchGenerationResult:
    source_products_considered: int
    reference_products_considered: int
    candidates_seen: int
    candidates_created: int
    candidates_skipped_existing: int


@dataclass(kw_only=True)
class _ComparableProduct:
    id: int
    source: str
    shop_id: int
    title: str
    normalized_title: str
    category_id: int | None
    category_raw: str | None


class ProductMatchCandidateGenerator:
    def __init__(self, session: Session) -> None:
        self._session = session

    def generate(self, filters: ProductMatchGenerationFilters) -> ProductMatchGenerationResult:
        source_products = self._eligible_unmatched_source_products(filters)
        references, canonical_id_by_reference_id = self._reference_products()
        candidates_seen = 0
        candidates_created = 0
        candidates_skipped_existing = 0

        for source_product in source_products:
            source = _source_comparable(source_product)
            for reference in references:
                if source_product.id == reference.id and reference.source != "canonical":
                    continue
                candidates = generate_product_match_candidates(
                    [source, reference],
                    min_confidence=filters.min_confidence,
                )
                if not candidates:
                    continue

                candidate = candidates[0]
                canonical_product_id = canonical_id_by_reference_id[reference.id]
                candidates_seen += 1
                if self._match_for_pair(
                    source_product_id=source_product.id,
                    canonical_product_id=canonical_product_id,
                ):
                    candidates_skipped_existing += 1
                    continue

                self._create_candidate(
                    source_product_id=source_product.id,
                    canonical_product_id=canonical_product_id,
                    candidate=candidate,
                )
                candidates_created += 1
                if candidates_created >= filters.limit:
                    return ProductMatchGenerationResult(
                        source_products_considered=len(source_products),
                        reference_products_considered=len(references),
                        candidates_seen=candidates_seen,
                        candidates_created=candidates_created,
                        candidates_skipped_existing=candidates_skipped_existing,
                    )

        return ProductMatchGenerationResult(
            source_products_considered=len(source_products),
            reference_products_considered=len(references),
            candidates_seen=candidates_seen,
            candidates_created=candidates_created,
            candidates_skipped_existing=candidates_skipped_existing,
        )

    def _eligible_unmatched_source_products(
        self,
        filters: ProductMatchGenerationFilters,
    ) -> list[SourceProduct]:
        accepted_source_ids = select(ProductMatch.source_product_id).where(
            ProductMatch.status == "accepted"
        )
        statement = (
            select(SourceProduct)
            .where(
                SourceProduct.is_active.is_(True),
                SourceProduct.id.not_in(accepted_source_ids),
            )
            .order_by(SourceProduct.category_id.asc(), SourceProduct.normalized_title.asc())
        )
        if filters.source is not None:
            source = filters.source.strip()
            if source:
                statement = statement.where(SourceProduct.source == source)
        if filters.shop_id is not None:
            statement = statement.where(SourceProduct.shop_id == filters.shop_id)
        if filters.category_id is not None:
            statement = statement.where(SourceProduct.category_id == filters.category_id)

        return [
            product
            for product in self._session.scalars(statement)
            if is_matchable_source_product(product.raw, is_not_product=product.is_not_product)
        ]

    def _reference_products(self) -> tuple[list[_ComparableProduct], dict[int, int]]:
        references: list[_ComparableProduct] = []
        canonical_id_by_reference_id: dict[int, int] = {}

        for canonical in self._session.scalars(
            select(CanonicalProduct).where(CanonicalProduct.match_status == "active")
        ):
            reference = _canonical_comparable(canonical)
            references.append(reference)
            canonical_id_by_reference_id[reference.id] = canonical.id

        accepted_statement = (
            select(SourceProduct, ProductMatch.canonical_product_id)
            .join(ProductMatch, ProductMatch.source_product_id == SourceProduct.id)
            .where(
                ProductMatch.status == "accepted",
                SourceProduct.is_active.is_(True),
            )
        )
        for product, canonical_product_id in self._session.execute(accepted_statement):
            reference = _source_comparable(product)
            references.append(reference)
            canonical_id_by_reference_id[reference.id] = canonical_product_id

        return references, canonical_id_by_reference_id

    def _match_for_pair(
        self,
        *,
        source_product_id: int,
        canonical_product_id: int,
    ) -> ProductMatch | None:
        return self._session.scalar(
            select(ProductMatch).where(
                ProductMatch.source_product_id == source_product_id,
                ProductMatch.canonical_product_id == canonical_product_id,
            )
        )

    def _create_candidate(
        self,
        *,
        source_product_id: int,
        canonical_product_id: int,
        candidate: ProductMatchCandidate,
    ) -> None:
        ProductMatchRepository(self._session).create(
            ProductMatchCreate(
                canonical_product_id=canonical_product_id,
                source_product_id=source_product_id,
                confidence=Decimal(str(candidate.confidence)).quantize(Decimal("0.001")),
                method=candidate.reason.method,
                status="candidate",
                reason=_reason_raw(candidate.reason),
            )
        )


def _source_comparable(product: SourceProduct) -> _ComparableProduct:
    return _ComparableProduct(
        id=product.id,
        source=product.source,
        shop_id=product.shop_id,
        title=product.title,
        normalized_title=product.normalized_title,
        category_id=product.category_id,
        category_raw=product.category_raw,
    )


def _canonical_comparable(product: CanonicalProduct) -> _ComparableProduct:
    return _ComparableProduct(
        id=-product.id,
        source="canonical",
        shop_id=0,
        title=product.title,
        normalized_title=product.normalized_title,
        category_id=product.category_id,
        category_raw=None,
    )


def _reason_raw(reason: ProductMatchReason) -> JsonObject:
    return {
        "matched_normalized_title": reason.matched_normalized_title,
        "exact_title": reason.exact_title,
        "token_overlap": list(reason.token_overlap),
        "left_only_tokens": list(reason.left_only_tokens),
        "right_only_tokens": list(reason.right_only_tokens),
        "ignored_tokens": list(reason.ignored_tokens),
        "blocked_by": list(reason.blocked_by),
        "token_similarity": reason.token_similarity,
        "same_category": reason.same_category,
    }
