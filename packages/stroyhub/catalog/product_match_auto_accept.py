from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from stroyhub.catalog.eligibility import is_matchable_source_product
from stroyhub.catalog.normalization_decisions import (
    NormalizationDecision,
    decide_normalization,
)
from stroyhub.catalog.product_match_generation import ProductMatchCandidateGenerator
from stroyhub.catalog.quality_pipeline import CatalogQualityPipeline
from stroyhub.catalog.query_helpers import escape_like_pattern
from stroyhub.models.tables import CanonicalProduct, ProductMatch, SourceProduct
from stroyhub.parsers.common import JsonObject

SAFE_AUTO_ACCEPT_METHODS = ("exact_normalized_title", "exact_title")


@dataclass(frozen=True, kw_only=True)
class ProductMatchAutoAcceptFilters:
    source: str | None = None
    shop_id: int | None = None
    category_id: int | None = None
    q: str | None = None
    min_confidence: Decimal = Decimal("1.000")
    methods: tuple[str, ...] = SAFE_AUTO_ACCEPT_METHODS
    limit: int = 100
    dry_run: bool = True
    actor: str | None = "auto"
    reason: str | None = None


@dataclass(frozen=True, kw_only=True)
class ProductMatchAutoAcceptItem:
    match_id: int
    canonical_product_id: int
    canonical_title: str
    source_product_id: int
    source_title: str
    confidence: Decimal
    method: str


@dataclass(frozen=True, kw_only=True)
class ProductMatchAutoAcceptResult:
    dry_run: bool
    candidates_seen: int
    would_accept: int
    accepted: int
    skipped_already_accepted: int
    skipped_ambiguous: int
    skipped_ineligible: int
    skipped_category_mismatch: int
    skipped_low_confidence: int
    skipped_method: int
    skipped_decision_review: int
    skipped_previously_rejected: int
    followup_candidates_created: int
    items: tuple[ProductMatchAutoAcceptItem, ...]


class ProductMatchAutoAcceptService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def run(self, filters: ProductMatchAutoAcceptFilters) -> ProductMatchAutoAcceptResult:
        rows = self._candidate_rows(filters)
        candidate_counts_by_source_product = Counter(
            match.source_product_id for match, _source_product, _canonical in rows
        )
        accepted_source_product_ids = self._accepted_source_product_ids(rows)
        rejected_pairs = self._rejected_pairs(rows)

        skipped_already_accepted = 0
        skipped_ambiguous_source_product_ids: set[int] = set()
        skipped_ineligible = 0
        skipped_category_mismatch = 0
        skipped_low_confidence = 0
        skipped_method = 0
        skipped_decision_review = 0
        skipped_previously_rejected = 0
        selected: list[
            tuple[ProductMatch, SourceProduct, CanonicalProduct, NormalizationDecision]
        ] = []

        for match, source_product, canonical in rows:
            if source_product.id in accepted_source_product_ids:
                skipped_already_accepted += 1
                continue
            if candidate_counts_by_source_product[source_product.id] != 1:
                skipped_ambiguous_source_product_ids.add(source_product.id)
                continue
            if not is_matchable_source_product(
                source_product.raw,
                is_not_product=source_product.is_not_product,
            ):
                skipped_ineligible += 1
                continue
            if match.method not in filters.methods:
                skipped_method += 1
                continue
            if match.confidence < filters.min_confidence:
                skipped_low_confidence += 1
                continue
            if (
                source_product.category_id is None
                or source_product.category_id != canonical.category_id
            ):
                skipped_category_mismatch += 1
                continue
            if (source_product.id, canonical.id) in rejected_pairs:
                skipped_previously_rejected += 1
                continue
            decision = decide_normalization(source_product, candidates=(canonical,))
            if (
                not decision.is_auto_accept
                or decision.action != "attach_to_existing"
                or decision.canonical_product_id != canonical.id
            ):
                skipped_decision_review += 1
                continue

            selected.append((match, source_product, canonical, decision))

        limited = selected[: filters.limit]
        accepted = 0
        followup_candidates_created = 0
        if not filters.dry_run:
            accepted = self._accept(limited, filters)
            followup_candidates_created = self._generate_followups(limited)
            self._refresh_quality_for_shops(
                {source_product.shop_id for _match, source_product, _canonical, _ in limited}
            )

        return ProductMatchAutoAcceptResult(
            dry_run=filters.dry_run,
            candidates_seen=len(rows),
            would_accept=len(limited),
            accepted=accepted,
            skipped_already_accepted=skipped_already_accepted,
            skipped_ambiguous=len(skipped_ambiguous_source_product_ids),
            skipped_ineligible=skipped_ineligible,
            skipped_category_mismatch=skipped_category_mismatch,
            skipped_low_confidence=skipped_low_confidence,
            skipped_method=skipped_method,
            skipped_decision_review=skipped_decision_review,
            skipped_previously_rejected=skipped_previously_rejected,
            followup_candidates_created=followup_candidates_created,
            items=tuple(
                _item(match, source_product, canonical)
                for match, source_product, canonical, _decision in limited
            ),
        )

    def _candidate_rows(
        self,
        filters: ProductMatchAutoAcceptFilters,
    ) -> list[tuple[ProductMatch, SourceProduct, CanonicalProduct]]:
        statement = (
            select(ProductMatch, SourceProduct, CanonicalProduct)
            .join(SourceProduct, ProductMatch.source_product_id == SourceProduct.id)
            .join(CanonicalProduct, ProductMatch.canonical_product_id == CanonicalProduct.id)
            .where(
                ProductMatch.status == "candidate",
                SourceProduct.is_active.is_(True),
                CanonicalProduct.match_status == "active",
            )
            .order_by(
                SourceProduct.id.asc(),
                ProductMatch.confidence.desc(),
                ProductMatch.id.asc(),
            )
        )
        if filters.source is not None:
            source = filters.source.strip()
            if source:
                statement = statement.where(SourceProduct.source == source)
        if filters.shop_id is not None:
            statement = statement.where(SourceProduct.shop_id == filters.shop_id)
        if filters.category_id is not None:
            statement = statement.where(SourceProduct.category_id == filters.category_id)
        if filters.q is not None:
            query = filters.q.strip()
            if query:
                pattern = f"%{escape_like_pattern(query)}%"
                statement = statement.where(
                    SourceProduct.title.ilike(pattern, escape="\\")
                    | SourceProduct.normalized_title.ilike(pattern.lower(), escape="\\")
                )

        return [tuple(row) for row in self._session.execute(statement)]

    def _accepted_source_product_ids(
        self,
        rows: list[tuple[ProductMatch, SourceProduct, CanonicalProduct]],
    ) -> set[int]:
        source_product_ids = [source_product.id for _match, source_product, _canonical in rows]
        if not source_product_ids:
            return set()

        return set(
            self._session.scalars(
                select(ProductMatch.source_product_id).where(
                    ProductMatch.status == "accepted",
                    ProductMatch.source_product_id.in_(source_product_ids),
                )
            )
        )

    def _rejected_pairs(
        self,
        rows: list[tuple[ProductMatch, SourceProduct, CanonicalProduct]],
    ) -> set[tuple[int, int]]:
        pairs_by_source_product_id: dict[int, set[int]] = defaultdict(set)
        for _match, source_product, canonical in rows:
            pairs_by_source_product_id[source_product.id].add(canonical.id)
        if not pairs_by_source_product_id:
            return set()

        source_product_ids = list(pairs_by_source_product_id)
        canonical_product_ids = sorted(
            {
                canonical_product_id
                for canonical_product_ids in pairs_by_source_product_id.values()
                for canonical_product_id in canonical_product_ids
            }
        )
        return {
            (source_product_id, canonical_product_id)
            for source_product_id, canonical_product_id in self._session.execute(
                select(
                    ProductMatch.source_product_id,
                    ProductMatch.canonical_product_id,
                ).where(
                    ProductMatch.status == "rejected",
                    ProductMatch.source_product_id.in_(source_product_ids),
                    ProductMatch.canonical_product_id.in_(canonical_product_ids),
                )
            )
        }

    def _accept(
        self,
        rows: list[tuple[ProductMatch, SourceProduct, CanonicalProduct, NormalizationDecision]],
        filters: ProductMatchAutoAcceptFilters,
    ) -> int:
        now = datetime.now(UTC)
        accepted = 0
        for match, _source_product, _canonical, decision in rows:
            if self._has_accepted_match(match.source_product_id):
                continue
            match.status = "accepted"
            match.reviewed_at = now
            match.reviewed_by = filters.actor
            match.reason = _reason(filters, decision=decision)
            accepted += 1

        self._session.flush()
        return accepted

    def _has_accepted_match(self, source_product_id: int) -> bool:
        return (
            self._session.scalar(
                select(ProductMatch.id).where(
                    ProductMatch.source_product_id == source_product_id,
                    ProductMatch.status == "accepted",
                )
            )
            is not None
        )

    def _generate_followups(
        self,
        rows: list[tuple[ProductMatch, SourceProduct, CanonicalProduct, NormalizationDecision]],
    ) -> int:
        canonical_product_ids = {
            canonical.id for _match, _source_product, canonical, _decision in rows
        }
        generator = ProductMatchCandidateGenerator(self._session)
        created = 0
        for canonical_product_id in sorted(canonical_product_ids):
            created += generator.generate_for_canonical(canonical_product_id).candidates_created
        return created

    def _refresh_quality_for_shops(self, shop_ids: set[int]) -> None:
        pipeline = CatalogQualityPipeline(self._session)
        for shop_id in sorted(shop_ids):
            pipeline.run_for_shop(shop_id, generate_candidates=False)


def _item(
    match: ProductMatch,
    source_product: SourceProduct,
    canonical: CanonicalProduct,
) -> ProductMatchAutoAcceptItem:
    return ProductMatchAutoAcceptItem(
        match_id=match.id,
        canonical_product_id=canonical.id,
        canonical_title=canonical.title,
        source_product_id=source_product.id,
        source_title=source_product.title,
        confidence=match.confidence,
        method=match.method,
    )


def _reason(
    filters: ProductMatchAutoAcceptFilters,
    *,
    decision: NormalizationDecision,
) -> JsonObject:
    reason: JsonObject = {
        "action": "auto_accept",
        "min_confidence": str(filters.min_confidence),
        "methods": list(filters.methods),
        "decision": decision.as_reason(),
    }
    if filters.reason is not None:
        reason["note"] = filters.reason
    return reason
