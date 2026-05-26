from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stroyhub.catalog.eligibility import is_matchable_source_product
from stroyhub.catalog.normalization_queue import (
    NormalizationQueueFilters,
    ProductNormalizationQueue,
)
from stroyhub.catalog.product_match_decisions import (
    ProductMatchDecisionConflict,
    ProductMatchDecisionInput,
    ProductMatchDecisionService,
)
from stroyhub.models.tables import ProductMatch, SourceProduct


@dataclass(frozen=True, kw_only=True)
class ProductBulkNormalizationFilters:
    source: str | None = None
    shop_id: int | None = None
    category_id: int | None = None
    q: str | None = None
    limit: int = 50
    offset: int = 0
    dry_run: bool = True
    actor: str | None = "admin"
    reason: str | None = None


@dataclass(frozen=True, kw_only=True)
class ProductBulkNormalizationItem:
    source_product_id: int
    title: str
    normalized_title: str
    canonical_product_id: int | None = None
    match_id: int | None = None


@dataclass(frozen=True, kw_only=True)
class ProductBulkNormalizationResult:
    dry_run: bool
    total: int
    page_size: int
    would_create: int
    created: int
    skipped_became_candidate: int
    skipped_already_accepted: int
    skipped_ineligible: int
    followup_candidates_created: int
    items: tuple[ProductBulkNormalizationItem, ...]


class ProductBulkNormalizationService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def run(
        self,
        filters: ProductBulkNormalizationFilters,
    ) -> ProductBulkNormalizationResult:
        page = ProductNormalizationQueue(self._session).list_items(
            NormalizationQueueFilters(
                state="eligible_unmatched",
                source=filters.source,
                shop_id=filters.shop_id,
                category_id=filters.category_id,
                q=filters.q,
                limit=filters.limit,
                offset=filters.offset,
            )
        )
        preview_items = tuple(
            ProductBulkNormalizationItem(
                source_product_id=item.id,
                title=item.title,
                normalized_title=item.normalized_title,
            )
            for item in page.items
        )
        if filters.dry_run:
            return ProductBulkNormalizationResult(
                dry_run=True,
                total=page.total,
                page_size=len(page.items),
                would_create=len(page.items),
                created=0,
                skipped_became_candidate=0,
                skipped_already_accepted=0,
                skipped_ineligible=0,
                followup_candidates_created=0,
                items=preview_items,
            )

        created_items: list[ProductBulkNormalizationItem] = []
        created = 0
        skipped_became_candidate = 0
        skipped_already_accepted = 0
        skipped_ineligible = 0
        followup_candidates_created = 0
        decision_service = ProductMatchDecisionService(self._session)

        for item in page.items:
            source_product = self._session.get(SourceProduct, item.id)
            if source_product is None or not source_product.is_active:
                skipped_ineligible += 1
                continue
            if not is_matchable_source_product(
                source_product.raw,
                is_not_product=source_product.is_not_product,
            ):
                skipped_ineligible += 1
                continue
            if self._has_match(source_product.id, status="accepted"):
                skipped_already_accepted += 1
                continue
            if self._has_match(source_product.id, status="candidate"):
                skipped_became_candidate += 1
                continue

            candidate_count_before = self._candidate_count()
            try:
                decision = decision_service.create_canonical_from_source_and_accept(
                    source_product_id=source_product.id,
                    data=ProductMatchDecisionInput(
                        actor=filters.actor,
                        reason=filters.reason,
                    ),
                )
            except ProductMatchDecisionConflict:
                if self._has_match(source_product.id, status="accepted"):
                    skipped_already_accepted += 1
                else:
                    skipped_became_candidate += 1
                continue

            followup_candidates_created += max(
                0,
                self._candidate_count() - candidate_count_before,
            )
            created += 1
            created_items.append(
                ProductBulkNormalizationItem(
                    source_product_id=source_product.id,
                    title=source_product.title,
                    normalized_title=source_product.normalized_title,
                    canonical_product_id=decision.canonical_product_id,
                    match_id=decision.id,
                )
            )

        return ProductBulkNormalizationResult(
            dry_run=False,
            total=page.total,
            page_size=len(page.items),
            would_create=len(page.items),
            created=created,
            skipped_became_candidate=skipped_became_candidate,
            skipped_already_accepted=skipped_already_accepted,
            skipped_ineligible=skipped_ineligible,
            followup_candidates_created=followup_candidates_created,
            items=tuple(created_items),
        )

    def _has_match(self, source_product_id: int, *, status: str) -> bool:
        return (
            self._session.scalar(
                select(ProductMatch.id).where(
                    ProductMatch.source_product_id == source_product_id,
                    ProductMatch.status == status,
                )
            )
            is not None
        )

    def _candidate_count(self) -> int:
        return (
            self._session.scalar(
                select(func.count())
                .select_from(ProductMatch)
                .where(ProductMatch.status == "candidate")
            )
            or 0
        )
