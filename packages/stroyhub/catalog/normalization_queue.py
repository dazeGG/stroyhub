from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import false, or_, select
from sqlalchemy.orm import Session

from stroyhub.catalog.products import ProductLatestPrice, ProductShop
from stroyhub.models.tables import (
    CanonicalProduct,
    Category,
    PriceSnapshot,
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


class ProductNormalizationQueue:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_items(self, filters: NormalizationQueueFilters) -> NormalizationQueuePage:
        rows = self._list_source_rows(filters)
        match_info_by_product_id = self._match_info_by_product_id(
            [product.id for product, *_ in rows]
        )
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

        if filters.state is not None:
            items = [item for item in items if item.state == filters.state]

        total = len(items)
        return NormalizationQueuePage(
            items=items[filters.offset : filters.offset + filters.limit],
            limit=filters.limit,
            offset=filters.offset,
            total=total,
        )

    def _list_source_rows(self, filters: NormalizationQueueFilters) -> list[tuple[Any, ...]]:
        latest_prices = (
            select(
                PriceSnapshot.source_product_id.label("source_product_id"),
                PriceSnapshot.price.label("latest_price"),
                PriceSnapshot.currency.label("latest_currency"),
                PriceSnapshot.unit_raw.label("latest_unit_raw"),
                PriceSnapshot.source_updated_at.label("latest_source_updated_at"),
                PriceSnapshot.parsed_at.label("latest_parsed_at"),
                PriceSnapshot.id.label("latest_snapshot_id"),
            )
            .distinct(PriceSnapshot.source_product_id)
            .order_by(
                PriceSnapshot.source_product_id,
                PriceSnapshot.parsed_at.desc(),
                PriceSnapshot.id.desc(),
            )
            .subquery()
        )
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
            .outerjoin(latest_prices, latest_prices.c.source_product_id == SourceProduct.id)
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
                pattern = f"%{_escape_like_pattern(query)}%"
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
                )
            elif match.status == "candidate":
                current = _MatchInfo(
                    accepted_match_id=current.accepted_match_id,
                    accepted_canonical_product_id=current.accepted_canonical_product_id,
                    accepted_canonical_title=current.accepted_canonical_title,
                    candidate_count=current.candidate_count + 1,
                    rejected_count=current.rejected_count,
                )
            elif match.status == "rejected":
                current = _MatchInfo(
                    accepted_match_id=current.accepted_match_id,
                    accepted_canonical_product_id=current.accepted_canonical_product_id,
                    accepted_canonical_title=current.accepted_canonical_title,
                    candidate_count=current.candidate_count,
                    rejected_count=current.rejected_count + 1,
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
        )

    def _category_filter_ids(self, category_id: int | None) -> set[int] | None:
        if category_id is None:
            return None

        category_rows = self._session.execute(select(Category.id, Category.parent_id))
        child_ids_by_parent: dict[int, list[int]] = {}
        known_ids: set[int] = set()
        for row_category_id, parent_id in category_rows:
            known_ids.add(row_category_id)
            if parent_id is not None:
                child_ids_by_parent.setdefault(parent_id, []).append(row_category_id)

        if category_id not in known_ids:
            return set()

        category_ids = {category_id}
        pending = [category_id]
        while pending:
            pending_id = pending.pop()
            for child_id in child_ids_by_parent.get(pending_id, []):
                if child_id not in category_ids:
                    category_ids.add(child_id)
                    pending.append(child_id)

        return category_ids


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


def _escape_like_pattern(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
