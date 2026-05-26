from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stroyhub.catalog.normalization_decisions import decide_normalization
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
    skipped_needs_review: int
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
        source_products_by_id = self._source_products_by_id([item.id for item in page.items])
        decisions_by_id = {
            product_id: decide_normalization(source_product, candidates=())
            for product_id, source_product in source_products_by_id.items()
        }
        preview_items = tuple(
            ProductBulkNormalizationItem(
                source_product_id=item.id,
                title=item.title,
                normalized_title=item.normalized_title,
            )
            for item in page.items
            if (decision := decisions_by_id.get(item.id)) is not None
            and decision.is_auto_accept
            and decision.action == "create_normalized_product"
        )
        if filters.dry_run:
            return ProductBulkNormalizationResult(
                dry_run=True,
                total=page.total,
                page_size=len(page.items),
                would_create=len(preview_items),
                created=0,
                skipped_became_candidate=0,
                skipped_already_accepted=0,
                skipped_ineligible=sum(
                    1
                    for decision in decisions_by_id.values()
                    if decision.status == "data_problem"
                ),
                skipped_needs_review=sum(
                    1
                    for decision in decisions_by_id.values()
                    if decision.status == "needs_review"
                ),
                followup_candidates_created=0,
                items=preview_items,
            )

        created_items: list[ProductBulkNormalizationItem] = []
        created = 0
        skipped_became_candidate = 0
        skipped_already_accepted = 0
        skipped_ineligible = 0
        skipped_needs_review = 0
        followup_candidates_created = 0
        decision_service = ProductMatchDecisionService(self._session)

        for item in page.items:
            source_product = source_products_by_id.get(item.id)
            if source_product is None or not source_product.is_active:
                skipped_ineligible += 1
                continue
            if self._has_match(source_product.id, status="accepted"):
                skipped_already_accepted += 1
                continue
            if self._has_match(source_product.id, status="candidate"):
                skipped_became_candidate += 1
                continue
            decision_contract = decisions_by_id.get(source_product.id) or decide_normalization(
                source_product,
                candidates=(),
            )
            if (
                not decision_contract.is_auto_accept
                or decision_contract.action != "create_normalized_product"
            ):
                if decision_contract.status == "data_problem":
                    skipped_ineligible += 1
                else:
                    skipped_needs_review += 1
                continue

            candidate_count_before = self._candidate_count()
            try:
                accepted_decision = decision_service.create_canonical_from_source_and_accept(
                    source_product_id=source_product.id,
                    data=ProductMatchDecisionInput(
                        actor=filters.actor,
                        reason=filters.reason,
                        decision=decision_contract.as_reason(),
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
                    canonical_product_id=accepted_decision.canonical_product_id,
                    match_id=accepted_decision.id,
                )
            )

        return ProductBulkNormalizationResult(
            dry_run=False,
            total=page.total,
            page_size=len(page.items),
            would_create=len(preview_items),
            created=created,
            skipped_became_candidate=skipped_became_candidate,
            skipped_already_accepted=skipped_already_accepted,
            skipped_ineligible=skipped_ineligible,
            skipped_needs_review=skipped_needs_review,
            followup_candidates_created=followup_candidates_created,
            items=tuple(created_items),
        )

    def _source_products_by_id(self, product_ids: list[int]) -> dict[int, SourceProduct]:
        if not product_ids:
            return {}
        return {
            product.id: product
            for product in self._session.scalars(
                select(SourceProduct).where(SourceProduct.id.in_(product_ids))
            )
        }

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
