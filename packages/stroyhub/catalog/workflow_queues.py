from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import and_, exists, false, func, not_, or_, select
from sqlalchemy.orm import Session

from stroyhub.catalog.product_match_decisions import (
    ProductMatchDecisionConflict,
    ProductMatchDecisionInput,
    ProductMatchDecisionNotFound,
    ProductMatchDecisionService,
)
from stroyhub.catalog.quality_pipeline import CatalogQualityPipeline
from stroyhub.catalog.query_helpers import (
    category_descendant_ids,
    escape_like_pattern,
    latest_price_subquery,
)
from stroyhub.models.tables import (
    CanonicalProduct,
    Category,
    ProductMatch,
    Shop,
    SourceProduct,
)
from stroyhub.parsers.common import JsonObject

CatalogWorkflowQueueName = Literal[
    "auto_acceptable",
    "review_needed",
    "data_problems",
    "possible_duplicates",
    "normalized_items",
]
CatalogWorkflowBatchItemStatus = Literal["would_accept", "accepted", "skipped"]


@dataclass(frozen=True, kw_only=True)
class CatalogWorkflowQueueFilters:
    source: str | None = None
    shop_id: int | None = None
    category_id: int | None = None
    q: str | None = None
    limit: int = 50
    offset: int = 0


@dataclass(frozen=True, kw_only=True)
class CatalogWorkflowDashboardCount:
    queue: CatalogWorkflowQueueName
    count: int


@dataclass(frozen=True, kw_only=True)
class CatalogWorkflowDashboard:
    counts: tuple[CatalogWorkflowDashboardCount, ...]


@dataclass(frozen=True, kw_only=True)
class CatalogWorkflowShop:
    id: int
    source: str
    source_id: str
    name: str


@dataclass(frozen=True, kw_only=True)
class CatalogWorkflowCategory:
    id: int
    slug: str
    name: str


@dataclass(frozen=True, kw_only=True)
class CatalogWorkflowLatestPrice:
    price: Decimal | None
    currency: str
    unit_raw: str | None
    source_updated_at: datetime | None
    parsed_at: datetime


@dataclass(frozen=True, kw_only=True)
class CatalogWorkflowReason:
    stage: str
    status: str | None
    action: str | None
    reasons: tuple[str, ...]
    blockers: tuple[str, ...]
    message: str | None = None


@dataclass(frozen=True, kw_only=True)
class CatalogWorkflowCandidateMatch:
    id: int
    canonical_product_id: int
    canonical_title: str
    canonical_normalized_title: str
    canonical_category_id: int | None
    confidence: Decimal
    method: str
    reason: JsonObject | None


@dataclass(frozen=True, kw_only=True)
class CatalogWorkflowMatchSummary:
    accepted_match_id: int | None
    accepted_canonical_product_id: int | None
    accepted_canonical_title: str | None
    candidate_count: int
    rejected_count: int


@dataclass(frozen=True, kw_only=True)
class CatalogWorkflowQueueItem:
    id: int
    queue: CatalogWorkflowQueueName
    source: str
    source_product_id: str | None
    title: str
    normalized_title: str
    category_id: int | None
    category: CatalogWorkflowCategory | None
    category_raw: str | None
    unit_raw: str | None
    image_url: str | None
    last_seen_at: datetime
    is_not_product: bool
    shop: CatalogWorkflowShop
    latest_price: CatalogWorkflowLatestPrice | None
    catalog_quality: JsonObject | None
    reasons: tuple[CatalogWorkflowReason, ...]
    match_summary: CatalogWorkflowMatchSummary
    candidate_matches: tuple[CatalogWorkflowCandidateMatch, ...]


@dataclass(frozen=True, kw_only=True)
class CatalogWorkflowQueuePage:
    queue: CatalogWorkflowQueueName
    items: tuple[CatalogWorkflowQueueItem, ...]
    limit: int
    offset: int
    total: int


@dataclass(frozen=True, kw_only=True)
class CatalogWorkflowAutoAcceptItem:
    source_product_id: int
    title: str
    action: str | None
    status: CatalogWorkflowBatchItemStatus
    reason: str
    canonical_product_id: int | None = None
    match_id: int | None = None


@dataclass(frozen=True, kw_only=True)
class CatalogWorkflowAutoAcceptResult:
    dry_run: bool
    total: int
    page_size: int
    would_accept: int
    accepted: int
    skipped: int
    items: tuple[CatalogWorkflowAutoAcceptItem, ...]


@dataclass(frozen=True, kw_only=True)
class _MatchInfo:
    accepted_match_id: int | None = None
    accepted_canonical_product_id: int | None = None
    accepted_canonical_title: str | None = None
    candidate_count: int = 0
    rejected_count: int = 0
    candidate_matches: tuple[CatalogWorkflowCandidateMatch, ...] = ()


class CatalogWorkflowQueueCatalog:
    def __init__(self, session: Session) -> None:
        self._session = session

    def dashboard(
        self,
        filters: CatalogWorkflowQueueFilters | None = None,
    ) -> CatalogWorkflowDashboard:
        selected_filters = filters or CatalogWorkflowQueueFilters(limit=1, offset=0)
        counts = tuple(
            CatalogWorkflowDashboardCount(
                queue=queue,
                count=self.count_queue(queue, selected_filters),
            )
            for queue in _QUEUE_ORDER
        )
        return CatalogWorkflowDashboard(counts=counts)

    def count_queue(
        self,
        queue: CatalogWorkflowQueueName,
        filters: CatalogWorkflowQueueFilters,
    ) -> int:
        statement = self._product_id_statement(queue, filters).order_by(None)
        return int(
            self._session.scalar(
                select(func.count()).select_from(statement.subquery())
            )
            or 0
        )

    def list_queue(
        self,
        queue: CatalogWorkflowQueueName,
        filters: CatalogWorkflowQueueFilters,
    ) -> CatalogWorkflowQueuePage:
        statement = self._product_id_statement(queue, filters)
        total = int(
            self._session.scalar(
                select(func.count()).select_from(statement.order_by(None).subquery())
            )
            or 0
        )
        product_ids = list(
            self._session.scalars(statement.limit(filters.limit).offset(filters.offset))
        )
        rows = self._list_source_rows(product_ids)
        match_info_by_product_id = self._match_info_by_product_id(product_ids)
        items = tuple(
            self._item(
                queue=queue,
                product=product,
                shop=shop,
                category=category,
                latest_price=latest_price,
                latest_currency=latest_currency,
                latest_unit_raw=latest_unit_raw,
                latest_source_updated_at=latest_source_updated_at,
                latest_parsed_at=latest_parsed_at,
                match_info=match_info_by_product_id.get(product.id, _MatchInfo()),
            )
            for (
                product,
                shop,
                category,
                latest_price,
                latest_currency,
                latest_unit_raw,
                latest_source_updated_at,
                latest_parsed_at,
            ) in rows
        )
        return CatalogWorkflowQueuePage(
            queue=queue,
            items=items,
            limit=filters.limit,
            offset=filters.offset,
            total=total,
        )

    def _product_id_statement(
        self,
        queue: CatalogWorkflowQueueName,
        filters: CatalogWorkflowQueueFilters,
    ) -> Any:
        statement = (
            select(SourceProduct.id)
            .join(Shop, SourceProduct.shop_id == Shop.id)
            .where(SourceProduct.is_active.is_(True))
            .order_by(SourceProduct.last_seen_at.desc(), SourceProduct.id.asc())
        )
        statement = self._apply_common_filters(statement, filters)
        return statement.where(_queue_predicate(queue))

    def _apply_common_filters(
        self,
        statement: Any,
        filters: CatalogWorkflowQueueFilters,
    ) -> Any:
        if filters.source is not None:
            source = filters.source.strip()
            if source:
                statement = statement.where(SourceProduct.source == source)
        if filters.shop_id is not None:
            statement = statement.where(SourceProduct.shop_id == filters.shop_id)
        if filters.q is not None:
            query = filters.q.strip()
            if query:
                pattern = f"%{escape_like_pattern(query)}%"
                statement = statement.where(
                    or_(
                        SourceProduct.title.ilike(pattern, escape="\\"),
                        SourceProduct.normalized_title.ilike(pattern.lower(), escape="\\"),
                    )
                )
        if (category_ids := self._category_filter_ids(filters.category_id)) is not None:
            if category_ids:
                statement = statement.where(SourceProduct.category_id.in_(category_ids))
            else:
                statement = statement.where(false())
        return statement

    def _category_filter_ids(self, category_id: int | None) -> set[int] | None:
        if category_id is None:
            return None
        return category_descendant_ids(self._session, {category_id})

    def _list_source_rows(self, product_ids: list[int]) -> list[tuple[Any, ...]]:
        if not product_ids:
            return []

        latest_prices = latest_price_subquery()
        statement = (
            select(
                SourceProduct,
                Shop,
                Category,
                latest_prices.c.latest_price,
                latest_prices.c.latest_currency,
                latest_prices.c.latest_unit_raw,
                latest_prices.c.latest_source_updated_at,
                latest_prices.c.latest_parsed_at,
            )
            .join(Shop, SourceProduct.shop_id == Shop.id)
            .outerjoin(Category, SourceProduct.category_id == Category.id)
            .outerjoin(
                latest_prices,
                and_(
                    latest_prices.c.source_product_id == SourceProduct.id,
                    latest_prices.c.row_number == 1,
                ),
            )
            .where(SourceProduct.id.in_(product_ids))
            .order_by(SourceProduct.last_seen_at.desc(), SourceProduct.id.asc())
        )
        return [tuple(row) for row in self._session.execute(statement)]

    def _match_info_by_product_id(self, product_ids: list[int]) -> dict[int, _MatchInfo]:
        if not product_ids:
            return {}

        statement = (
            select(ProductMatch, CanonicalProduct)
            .join(CanonicalProduct, ProductMatch.canonical_product_id == CanonicalProduct.id)
            .where(ProductMatch.source_product_id.in_(product_ids))
            .order_by(ProductMatch.id.asc())
        )
        info_by_product_id: dict[int, _MatchInfo] = {}
        for match, canonical in self._session.execute(statement):
            current = info_by_product_id.get(match.source_product_id, _MatchInfo())
            if match.status == "accepted":
                current = _MatchInfo(
                    accepted_match_id=match.id,
                    accepted_canonical_product_id=canonical.id,
                    accepted_canonical_title=canonical.title,
                    candidate_count=current.candidate_count,
                    rejected_count=current.rejected_count,
                    candidate_matches=current.candidate_matches,
                )
            elif match.status == "candidate":
                current = _MatchInfo(
                    accepted_match_id=current.accepted_match_id,
                    accepted_canonical_product_id=current.accepted_canonical_product_id,
                    accepted_canonical_title=current.accepted_canonical_title,
                    candidate_count=current.candidate_count + 1,
                    rejected_count=current.rejected_count,
                    candidate_matches=(
                        *current.candidate_matches,
                        CatalogWorkflowCandidateMatch(
                            id=match.id,
                            canonical_product_id=canonical.id,
                            canonical_title=canonical.title,
                            canonical_normalized_title=canonical.normalized_title,
                            canonical_category_id=canonical.category_id,
                            confidence=match.confidence,
                            method=match.method,
                            reason=match.reason,
                        ),
                    ),
                )
            elif match.status == "rejected":
                current = _MatchInfo(
                    accepted_match_id=current.accepted_match_id,
                    accepted_canonical_product_id=current.accepted_canonical_product_id,
                    accepted_canonical_title=current.accepted_canonical_title,
                    candidate_count=current.candidate_count,
                    rejected_count=current.rejected_count + 1,
                    candidate_matches=current.candidate_matches,
                )
            info_by_product_id[match.source_product_id] = current

        return info_by_product_id

    def _item(
        self,
        *,
        queue: CatalogWorkflowQueueName,
        product: SourceProduct,
        shop: Shop,
        category: Category | None,
        latest_price: Decimal | None,
        latest_currency: str | None,
        latest_unit_raw: str | None,
        latest_source_updated_at: datetime | None,
        latest_parsed_at: datetime | None,
        match_info: _MatchInfo,
    ) -> CatalogWorkflowQueueItem:
        latest = None
        if latest_parsed_at is not None:
            latest = CatalogWorkflowLatestPrice(
                price=latest_price,
                currency=latest_currency or "RUB",
                unit_raw=latest_unit_raw,
                source_updated_at=latest_source_updated_at,
                parsed_at=latest_parsed_at,
            )

        quality = _catalog_quality(product.raw)
        return CatalogWorkflowQueueItem(
            id=product.id,
            queue=queue,
            source=product.source,
            source_product_id=product.source_product_id,
            title=product.title,
            normalized_title=product.normalized_title,
            category_id=product.category_id,
            category=(
                CatalogWorkflowCategory(
                    id=category.id,
                    slug=category.slug,
                    name=category.name,
                )
                if category is not None
                else None
            ),
            category_raw=product.category_raw,
            unit_raw=product.unit_raw,
            image_url=product.image_url,
            last_seen_at=product.last_seen_at,
            is_not_product=product.is_not_product,
            shop=CatalogWorkflowShop(
                id=shop.id,
                source=shop.source,
                source_id=shop.source_id,
                name=shop.name,
            ),
            latest_price=latest,
            catalog_quality=quality,
            reasons=_workflow_reasons(product.raw),
            match_summary=CatalogWorkflowMatchSummary(
                accepted_match_id=match_info.accepted_match_id,
                accepted_canonical_product_id=match_info.accepted_canonical_product_id,
                accepted_canonical_title=match_info.accepted_canonical_title,
                candidate_count=match_info.candidate_count,
                rejected_count=match_info.rejected_count,
            ),
            candidate_matches=match_info.candidate_matches,
        )


class CatalogWorkflowAutoAcceptService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def run(
        self,
        filters: CatalogWorkflowQueueFilters,
        *,
        dry_run: bool,
        actor: str | None,
        reason: str | None,
    ) -> CatalogWorkflowAutoAcceptResult:
        page = CatalogWorkflowQueueCatalog(self._session).list_queue(
            "auto_acceptable",
            filters,
        )
        products = self._source_products_by_id([item.id for item in page.items])
        decision_service = ProductMatchDecisionService(
            self._session,
            refresh_quality_on_accept=False,
        )
        results: list[CatalogWorkflowAutoAcceptItem] = []
        affected_shop_ids: set[int] = set()

        for item in page.items:
            product = products.get(item.id)
            snapshot_normalization = _normalization_from_quality(item.catalog_quality)
            action = _normalization_action(snapshot_normalization)
            if product is None or not product.is_active:
                results.append(_batch_skip(item, action=action, reason="source_product_not_found"))
                continue
            if self._has_accepted_match(product.id):
                results.append(_batch_skip(item, action=action, reason="already_accepted"))
                continue
            if action not in {"create_normalized_product", "attach_to_existing"}:
                results.append(_batch_skip(item, action=action, reason="unsupported_action"))
                continue
            canonical_product_id = _normalization_canonical_product_id(
                snapshot_normalization
            )
            if action == "attach_to_existing" and canonical_product_id is None:
                results.append(
                    _batch_skip(
                        item,
                        action=action,
                        reason="missing_canonical_product_id",
                    )
                )
                continue

            if dry_run:
                results.append(
                    CatalogWorkflowAutoAcceptItem(
                        source_product_id=item.id,
                        title=item.title,
                        action=action,
                        status="would_accept",
                        reason="dry_run",
                        canonical_product_id=canonical_product_id,
                    )
                )
                continue

            try:
                if action == "create_normalized_product":
                    decision = decision_service.create_canonical_from_source_and_accept(
                        source_product_id=product.id,
                        data=ProductMatchDecisionInput(
                            actor=actor,
                            reason=reason,
                            decision=snapshot_normalization,
                        ),
                    )
                else:
                    decision = decision_service.accept_existing(
                        canonical_product_id=canonical_product_id or 0,
                        source_product_id=product.id,
                        data=ProductMatchDecisionInput(
                            actor=actor,
                            reason=reason,
                            decision=snapshot_normalization,
                        ),
                    )
            except (ProductMatchDecisionConflict, ProductMatchDecisionNotFound) as exc:
                results.append(_batch_skip(item, action=action, reason=str(exc)))
                continue

            results.append(
                CatalogWorkflowAutoAcceptItem(
                    source_product_id=item.id,
                    title=item.title,
                    action=action,
                    status="accepted",
                    reason="accepted",
                    canonical_product_id=decision.canonical_product_id,
                    match_id=decision.id,
                )
            )
            affected_shop_ids.add(product.shop_id)

        if not dry_run:
            for shop_id in sorted(affected_shop_ids):
                CatalogQualityPipeline(self._session).run_for_shop(
                    shop_id,
                    generate_candidates=False,
                )

        return CatalogWorkflowAutoAcceptResult(
            dry_run=dry_run,
            total=page.total,
            page_size=len(page.items),
            would_accept=sum(1 for item in results if item.status == "would_accept"),
            accepted=sum(1 for item in results if item.status == "accepted"),
            skipped=sum(1 for item in results if item.status == "skipped"),
            items=tuple(results),
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


def _queue_predicate(queue: CatalogWorkflowQueueName) -> Any:
    accepted_exists = _accepted_exists()
    candidate_exists = _candidate_exists()
    eligibility_status = SourceProduct.raw["catalog_eligibility"]["status"].astext
    pipeline_status = SourceProduct.raw["catalog_quality"]["status"].astext
    categorization_status = SourceProduct.raw["catalog_quality"]["categorization"][
        "status"
    ].astext
    normalization_status = SourceProduct.raw["catalog_quality"]["normalization"][
        "status"
    ].astext
    normalization_action = SourceProduct.raw["catalog_quality"]["normalization"][
        "action"
    ].astext
    not_accepted = not_(accepted_exists)

    if queue == "auto_acceptable":
        return and_(
            not_accepted,
            SourceProduct.is_not_product.is_(False),
            pipeline_status == "processed",
            categorization_status == "assigned",
            normalization_status == "ready_to_accept",
            or_(
                normalization_action == "create_normalized_product",
                and_(normalization_action == "attach_to_existing", candidate_exists),
            ),
        )
    if queue == "review_needed":
        return and_(
            not_accepted,
            SourceProduct.is_not_product.is_(False),
            or_(
                eligibility_status == "needs_review",
                categorization_status == "needs_review",
                normalization_status == "needs_review",
            ),
        )
    if queue == "data_problems":
        return or_(
            SourceProduct.is_not_product.is_(True),
            eligibility_status == "ineligible",
            pipeline_status == "failed",
            normalization_status == "data_problem",
        )
    if queue == "possible_duplicates":
        return and_(not_accepted, candidate_exists)
    return accepted_exists


def _accepted_exists() -> Any:
    return exists(
        select(ProductMatch.id).where(
            ProductMatch.source_product_id == SourceProduct.id,
            ProductMatch.status == "accepted",
        )
    )


def _candidate_exists() -> Any:
    return exists(
        select(ProductMatch.id).where(
            ProductMatch.source_product_id == SourceProduct.id,
            ProductMatch.status == "candidate",
        )
    )


def _catalog_quality(raw: JsonObject | None) -> JsonObject | None:
    if raw is None:
        return None
    value = raw.get("catalog_quality")
    return value if isinstance(value, dict) else None


def _normalization_raw(raw: JsonObject | None) -> JsonObject | None:
    quality = _catalog_quality(raw)
    return _normalization_from_quality(quality)


def _normalization_from_quality(quality: JsonObject | None) -> JsonObject | None:
    if quality is None:
        return None
    value = quality.get("normalization")
    return value if isinstance(value, dict) else None


def _normalization_action(normalization: JsonObject | None) -> str | None:
    if normalization is None:
        return None
    value = normalization.get("action")
    return value if isinstance(value, str) else None


def _normalization_canonical_product_id(normalization: JsonObject | None) -> int | None:
    if normalization is None:
        return None
    value = normalization.get("canonical_product_id")
    return value if isinstance(value, int) else None


def _workflow_reasons(raw: JsonObject | None) -> tuple[CatalogWorkflowReason, ...]:
    reasons: list[CatalogWorkflowReason] = []
    if raw is None:
        return ()

    eligibility = raw.get("catalog_eligibility")
    if isinstance(eligibility, dict):
        reasons.append(
            CatalogWorkflowReason(
                stage="catalog_eligibility",
                status=_string_value(eligibility.get("status")),
                action=None,
                reasons=_string_tuple(eligibility.get("reasons")),
                blockers=(),
            )
        )

    quality = _catalog_quality(raw)
    if quality is None:
        return tuple(reasons)

    pipeline_error = _string_value(quality.get("error"))
    reasons.append(
        CatalogWorkflowReason(
            stage="pipeline",
            status=_string_value(quality.get("status")),
            action=None,
            reasons=(),
            blockers=(),
            message=pipeline_error,
        )
    )
    for stage in ("cleanup", "attributes", "categorization", "normalization"):
        value = quality.get(stage)
        if not isinstance(value, dict):
            continue
        reasons.append(
            CatalogWorkflowReason(
                stage=stage,
                status=_string_value(value.get("status")),
                action=_string_value(value.get("action")),
                reasons=_string_tuple(value.get("reasons")),
                blockers=_string_tuple(value.get("blockers")),
                message=_string_value(value.get("error")),
            )
        )

    return tuple(reasons)


def _batch_skip(
    item: CatalogWorkflowQueueItem,
    *,
    action: str | None,
    reason: str,
) -> CatalogWorkflowAutoAcceptItem:
    return CatalogWorkflowAutoAcceptItem(
        source_product_id=item.id,
        title=item.title,
        action=action,
        status="skipped",
        reason=reason,
    )


def _string_value(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value)


_QUEUE_ORDER: tuple[CatalogWorkflowQueueName, ...] = (
    "auto_acceptable",
    "review_needed",
    "data_problems",
    "possible_duplicates",
    "normalized_items",
)
