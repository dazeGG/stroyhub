from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import and_, exists, false, func, not_, or_, select
from sqlalchemy.orm import Session

from stroyhub.catalog.products import ProductLatestPrice, ProductShop
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

NormalizationQueueState = Literal[
    "ineligible",
    "needs_review",
    "eligible_unmatched",
    "candidate_match",
    "accepted",
]


@dataclass(frozen=True, kw_only=True)
class NormalizationQueueFilters:
    state: NormalizationQueueState | None = None
    source: str | None = None
    shop_id: int | None = None
    category_id: int | None = None
    q: str | None = None
    limit: int = 50
    offset: int = 0


@dataclass(frozen=True, kw_only=True)
class CatalogEligibilityInfo:
    status: str
    confidence: str | None
    score: int | None
    reasons: tuple[str, ...]


@dataclass(frozen=True, kw_only=True)
class NormalizationMatchSummary:
    accepted_match_id: int | None
    accepted_canonical_product_id: int | None
    accepted_canonical_title: str | None
    candidate_count: int
    rejected_count: int


@dataclass(frozen=True, kw_only=True)
class NormalizationCandidateMatch:
    id: int
    canonical_product_id: int
    canonical_title: str
    canonical_normalized_title: str
    canonical_category_id: int | None
    confidence: Decimal
    method: str
    reason: JsonObject | None


@dataclass(frozen=True, kw_only=True)
class NormalizationQueueItem:
    id: int
    state: NormalizationQueueState
    source: str
    source_product_id: str | None
    title: str
    normalized_title: str
    category_id: int | None
    category_slug: str | None
    category_name: str | None
    category_raw: str | None
    unit_raw: str | None
    image_url: str | None
    last_seen_at: datetime
    is_not_product: bool
    shop: ProductShop
    latest_price: ProductLatestPrice | None
    catalog_eligibility: CatalogEligibilityInfo | None
    match_summary: NormalizationMatchSummary
    candidate_matches: tuple[NormalizationCandidateMatch, ...]


@dataclass(frozen=True, kw_only=True)
class NormalizationQueuePage:
    items: list[NormalizationQueueItem]
    limit: int
    offset: int
    total: int


@dataclass(frozen=True, kw_only=True)
class _MatchInfo:
    accepted_match_id: int | None = None
    accepted_canonical_product_id: int | None = None
    accepted_canonical_title: str | None = None
    candidate_count: int = 0
    rejected_count: int = 0
    candidate_matches: tuple[NormalizationCandidateMatch, ...] = ()


class ProductNormalizationQueue:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_items(self, filters: NormalizationQueueFilters) -> NormalizationQueuePage:
        product_ids, total = self._page_product_ids(filters)
        rows = self._list_source_rows(product_ids)
        match_info_by_product_id = self._match_info_by_product_id(product_ids)
        items = [
            self._queue_item(
                product,
                shop,
                category,
                latest_price,
                latest_currency,
                latest_unit_raw,
                latest_source_updated_at,
                latest_parsed_at,
                match_info_by_product_id.get(product.id, _MatchInfo()),
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
        ]

        return NormalizationQueuePage(
            items=items,
            limit=filters.limit,
            offset=filters.offset,
            total=total,
        )

    def _page_product_ids(self, filters: NormalizationQueueFilters) -> tuple[list[int], int]:
        statement = self._product_id_statement(filters)
        total = self._session.scalar(
            select(func.count()).select_from(statement.order_by(None).subquery())
        )
        page_statement = statement.limit(filters.limit).offset(filters.offset)
        product_ids = list(self._session.scalars(page_statement))
        return product_ids, total or 0

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
            .where(SourceProduct.is_active.is_(True))
            .where(SourceProduct.id.in_(product_ids))
            .order_by(SourceProduct.last_seen_at.desc(), SourceProduct.id.asc())
        )

        return [tuple(row) for row in self._session.execute(statement)]

    def _product_id_statement(self, filters: NormalizationQueueFilters) -> Any:
        statement = (
            select(SourceProduct.id)
            .join(Shop, SourceProduct.shop_id == Shop.id)
            .where(SourceProduct.is_active.is_(True))
            .order_by(SourceProduct.last_seen_at.desc(), SourceProduct.id.asc())
        )

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
        if filters.state is not None:
            statement = statement.where(self._state_predicate(filters.state))

        return statement

    def _state_predicate(self, state: NormalizationQueueState) -> Any:
        eligibility_status = SourceProduct.raw["catalog_eligibility"]["status"].astext
        accepted_exists = exists(
            select(ProductMatch.id).where(
                ProductMatch.source_product_id == SourceProduct.id,
                ProductMatch.status == "accepted",
            )
        )
        candidate_exists = exists(
            select(ProductMatch.id).where(
                ProductMatch.source_product_id == SourceProduct.id,
                ProductMatch.status == "candidate",
            )
        )
        ineligible = or_(
            SourceProduct.is_not_product.is_(True),
            eligibility_status == "ineligible",
        )
        eligible_for_matching = and_(
            not_(ineligible),
            or_(
                eligibility_status.is_(None),
                eligibility_status != "needs_review",
            ),
        )

        if state == "ineligible":
            return ineligible
        if state == "needs_review":
            return and_(not_(ineligible), eligibility_status == "needs_review")
        if state == "accepted":
            return and_(eligible_for_matching, accepted_exists)
        if state == "candidate_match":
            return and_(eligible_for_matching, not_(accepted_exists), candidate_exists)
        return and_(eligible_for_matching, not_(accepted_exists), not_(candidate_exists))

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
                        NormalizationCandidateMatch(
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

    def _queue_item(
        self,
        product: SourceProduct,
        shop: Shop,
        category: Category | None,
        latest_price: Decimal | None,
        latest_currency: str | None,
        latest_unit_raw: str | None,
        latest_source_updated_at: datetime | None,
        latest_parsed_at: datetime | None,
        match_info: _MatchInfo,
    ) -> NormalizationQueueItem:
        latest = None
        if latest_parsed_at is not None:
            latest = ProductLatestPrice(
                price=latest_price,
                currency=latest_currency or "RUB",
                unit_raw=latest_unit_raw,
                source_updated_at=latest_source_updated_at,
                parsed_at=latest_parsed_at,
            )

        eligibility = _catalog_eligibility(product.raw)
        state = _queue_state(product, eligibility=eligibility, match_info=match_info)
        return NormalizationQueueItem(
            id=product.id,
            state=state,
            source=product.source,
            source_product_id=product.source_product_id,
            title=product.title,
            normalized_title=product.normalized_title,
            category_id=product.category_id,
            category_slug=category.slug if category is not None else None,
            category_name=category.name if category is not None else None,
            category_raw=product.category_raw,
            unit_raw=product.unit_raw,
            image_url=product.image_url,
            last_seen_at=product.last_seen_at,
            is_not_product=product.is_not_product,
            shop=ProductShop(
                id=shop.id,
                source=shop.source,
                source_id=shop.source_id,
                name=shop.name,
            ),
            latest_price=latest,
            catalog_eligibility=eligibility,
            match_summary=NormalizationMatchSummary(
                accepted_match_id=match_info.accepted_match_id,
                accepted_canonical_product_id=match_info.accepted_canonical_product_id,
                accepted_canonical_title=match_info.accepted_canonical_title,
                candidate_count=match_info.candidate_count,
                rejected_count=match_info.rejected_count,
            ),
            candidate_matches=match_info.candidate_matches,
        )

    def _category_filter_ids(self, category_id: int | None) -> set[int] | None:
        if category_id is None:
            return None
        return category_descendant_ids(self._session, {category_id})


def _queue_state(
    product: SourceProduct,
    *,
    eligibility: CatalogEligibilityInfo | None,
    match_info: _MatchInfo,
) -> NormalizationQueueState:
    eligibility_status = eligibility.status if eligibility is not None else None
    if product.is_not_product or eligibility_status == "ineligible":
        return "ineligible"
    if eligibility_status == "needs_review":
        return "needs_review"
    if match_info.accepted_match_id is not None:
        return "accepted"
    if match_info.candidate_count > 0:
        return "candidate_match"
    return "eligible_unmatched"


def _catalog_eligibility(raw: JsonObject | None) -> CatalogEligibilityInfo | None:
    if raw is None:
        return None

    value = raw.get("catalog_eligibility")
    if not isinstance(value, dict):
        return None

    reasons = value.get("reasons")
    return CatalogEligibilityInfo(
        status=str(value.get("status") or "eligible"),
        confidence=_optional_string(value.get("confidence")),
        score=value.get("score") if isinstance(value.get("score"), int) else None,
        reasons=tuple(str(reason) for reason in reasons) if isinstance(reasons, list) else (),
    )


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    return str(value)
