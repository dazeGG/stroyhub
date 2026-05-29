from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, false, func, or_, select
from sqlalchemy.orm import Session

from stroyhub.catalog.eligibility import is_matchable_source_product
from stroyhub.catalog.products import format_price_text
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


@dataclass(frozen=True, kw_only=True)
class CanonicalProductFilters:
    q: str | None = None
    category_id: int | None = None
    match_status: str | None = None
    limit: int = 50
    offset: int = 0


@dataclass(frozen=True, kw_only=True)
class CanonicalProductMatchCounts:
    accepted: int
    candidate: int
    rejected: int


@dataclass(frozen=True, kw_only=True)
class CanonicalProductCategory:
    id: int
    slug: str
    name: str


@dataclass(frozen=True, kw_only=True)
class CanonicalProductItem:
    id: int
    title: str
    normalized_title: str
    category_id: int | None
    category: CanonicalProductCategory | None
    brand: str | None
    model: str | None
    unit_raw: str | None
    attributes: JsonObject | None
    match_status: str
    created_at: datetime
    updated_at: datetime
    match_counts: CanonicalProductMatchCounts


@dataclass(frozen=True, kw_only=True)
class CanonicalLinkedSourceProduct:
    id: int
    match_id: int
    source: str
    source_product_id: str | None
    title: str
    normalized_title: str
    shop_id: int
    shop_name: str
    shop_source_id: str
    category_raw: str | None
    unit_raw: str | None
    source_url: str | None
    image_url: str | None
    last_seen_at: datetime
    latest_price: "CanonicalSourceLatestPrice | None"
    confidence: Decimal


@dataclass(frozen=True, kw_only=True)
class CanonicalSourceLatestPrice:
    price: Decimal | None
    price_kind: str
    price_text: str | None
    currency: str
    unit_raw: str | None
    source_updated_at: datetime | None
    parsed_at: datetime


@dataclass(frozen=True, kw_only=True)
class CanonicalOfferGroup:
    source: str
    shop_id: int
    shop_source_id: str
    shop_name: str
    items: list[CanonicalLinkedSourceProduct]


@dataclass(frozen=True, kw_only=True)
class CanonicalProductDetail(CanonicalProductItem):
    accepted_source_products: list[CanonicalLinkedSourceProduct]
    accepted_offer_groups: list[CanonicalOfferGroup]
    candidate_source_products: list[CanonicalLinkedSourceProduct]
    rejected_source_products: list[CanonicalLinkedSourceProduct]


@dataclass(frozen=True, kw_only=True)
class CanonicalProductPage:
    items: list[CanonicalProductItem]
    limit: int
    offset: int
    total: int


class CanonicalProductCatalog:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_products(self, filters: CanonicalProductFilters) -> CanonicalProductPage:
        statement = self._base_statement()
        statement = self._apply_filters(statement, filters)
        statement = (
            statement.order_by(CanonicalProduct.normalized_title.asc(), CanonicalProduct.id.asc())
            .limit(filters.limit)
            .offset(filters.offset)
        )
        rows = list(self._session.execute(statement))
        counts = self._match_counts_by_canonical_id([product.id for product, _category in rows])

        return CanonicalProductPage(
            items=[
                self._item(product, category, counts.get(product.id))
                for product, category in rows
            ],
            limit=filters.limit,
            offset=filters.offset,
            total=self.count_products(filters),
        )

    def count_products(self, filters: CanonicalProductFilters) -> int:
        statement = select(func.count(CanonicalProduct.id)).outerjoin(
            Category, CanonicalProduct.category_id == Category.id
        )
        statement = self._apply_filters(statement, filters)
        return int(self._session.scalar(statement) or 0)

    def get_detail(self, product_id: int) -> CanonicalProductDetail | None:
        row = self._session.execute(
            self._base_statement().where(CanonicalProduct.id == product_id)
        ).first()
        if row is None:
            return None

        product, category = row
        counts = self._match_counts_by_canonical_id([product.id]).get(product.id)
        item = self._item(product, category, counts)
        accepted_products = self._source_products_for_status(product.id, status="accepted")
        return CanonicalProductDetail(
            **item.__dict__,
            accepted_source_products=accepted_products,
            accepted_offer_groups=_offer_groups(accepted_products),
            candidate_source_products=self._source_products_for_status(
                product.id,
                status="candidate",
            ),
            rejected_source_products=self._source_products_for_status(
                product.id,
                status="rejected",
            ),
        )

    def _base_statement(self) -> Any:
        return (
            select(CanonicalProduct, Category)
            .outerjoin(Category, CanonicalProduct.category_id == Category.id)
        )

    def _apply_filters(self, statement: Any, filters: CanonicalProductFilters) -> Any:
        if filters.q is not None:
            query = filters.q.strip()
            if query:
                pattern = f"%{escape_like_pattern(query)}%"
                statement = statement.where(
                    or_(
                        CanonicalProduct.title.ilike(pattern, escape="\\"),
                        CanonicalProduct.normalized_title.ilike(
                            pattern.lower(), escape="\\"
                        ),
                    )
                )
        if filters.match_status is not None:
            status = filters.match_status.strip()
            if status:
                statement = statement.where(CanonicalProduct.match_status == status)
        if (category_ids := self._category_filter_ids(filters.category_id)) is not None:
            if category_ids:
                statement = statement.where(CanonicalProduct.category_id.in_(category_ids))
            else:
                statement = statement.where(false())

        return statement

    def _match_counts_by_canonical_id(
        self, canonical_ids: list[int]
    ) -> dict[int, CanonicalProductMatchCounts]:
        if not canonical_ids:
            return {}

        rows = self._session.execute(
            select(
                ProductMatch.canonical_product_id,
                ProductMatch.status,
                func.count(ProductMatch.id),
            )
            .where(ProductMatch.canonical_product_id.in_(canonical_ids))
            .group_by(ProductMatch.canonical_product_id, ProductMatch.status)
        )
        count_values: dict[int, dict[str, int]] = {}
        for canonical_id, status, count in rows:
            count_values.setdefault(canonical_id, {})[status] = int(count)

        return {
            canonical_id: CanonicalProductMatchCounts(
                accepted=values.get("accepted", 0),
                candidate=values.get("candidate", 0),
                rejected=values.get("rejected", 0),
            )
            for canonical_id, values in count_values.items()
        }

    def _source_products_for_status(
        self,
        canonical_product_id: int,
        *,
        status: str,
    ) -> list[CanonicalLinkedSourceProduct]:
        latest_prices = latest_price_subquery()
        statement = (
            select(
                ProductMatch,
                SourceProduct,
                Shop,
                latest_prices.c.latest_price,
                latest_prices.c.latest_price_kind,
                latest_prices.c.latest_currency,
                latest_prices.c.latest_unit_raw,
                latest_prices.c.latest_source_updated_at,
                latest_prices.c.latest_parsed_at,
            )
            .join(ProductMatch, ProductMatch.source_product_id == SourceProduct.id)
            .join(Shop, SourceProduct.shop_id == Shop.id)
            .outerjoin(
                latest_prices,
                and_(
                    latest_prices.c.source_product_id == SourceProduct.id,
                    latest_prices.c.row_number == 1,
                ),
            )
            .where(
                ProductMatch.canonical_product_id == canonical_product_id,
                ProductMatch.status == status,
                SourceProduct.is_active.is_(True),
            )
            .order_by(Shop.name.asc(), SourceProduct.normalized_title.asc(), SourceProduct.id.asc())
        )
        return [
            CanonicalLinkedSourceProduct(
                id=product.id,
                match_id=match.id,
                source=product.source,
                source_product_id=product.source_product_id,
                title=product.title,
                normalized_title=product.normalized_title,
                shop_id=shop.id,
                shop_name=shop.name,
                shop_source_id=shop.source_id,
                category_raw=product.category_raw,
                unit_raw=product.unit_raw,
                source_url=_source_url(product.raw),
                image_url=product.image_url,
                last_seen_at=product.last_seen_at,
                latest_price=(
                    CanonicalSourceLatestPrice(
                        price=latest_price,
                        price_kind=latest_price_kind or "exact",
                        price_text=format_price_text(
                            price=latest_price,
                            currency=latest_currency or "RUB",
                            price_kind=latest_price_kind or "exact",
                        ),
                        currency=latest_currency or "RUB",
                        unit_raw=latest_unit_raw,
                        source_updated_at=latest_source_updated_at,
                        parsed_at=latest_parsed_at,
                    )
                    if latest_parsed_at is not None
                    else None
                ),
                confidence=match.confidence,
            )
            for (
                match,
                product,
                shop,
                latest_price,
                latest_price_kind,
                latest_currency,
                latest_unit_raw,
                latest_source_updated_at,
                latest_parsed_at,
            ) in self._session.execute(statement)
            if is_matchable_source_product(
                product.raw,
                is_not_product=product.is_not_product,
            )
        ]

    def _item(
        self,
        product: CanonicalProduct,
        category: Category | None,
        counts: CanonicalProductMatchCounts | None,
    ) -> CanonicalProductItem:
        return CanonicalProductItem(
            id=product.id,
            title=product.title,
            normalized_title=product.normalized_title,
            category_id=product.category_id,
            category=(
                CanonicalProductCategory(
                    id=category.id,
                    slug=category.slug,
                    name=category.name,
                )
                if category is not None
                else None
            ),
            brand=product.brand,
            model=product.model,
            unit_raw=product.unit_raw,
            attributes=product.attributes,
            match_status=product.match_status,
            created_at=product.created_at,
            updated_at=product.updated_at,
            match_counts=counts
            or CanonicalProductMatchCounts(accepted=0, candidate=0, rejected=0),
        )

    def _category_filter_ids(self, category_id: int | None) -> set[int] | None:
        if category_id is None:
            return None
        return category_descendant_ids(self._session, {category_id})


def _offer_groups(
    products: list[CanonicalLinkedSourceProduct],
) -> list[CanonicalOfferGroup]:
    groups: dict[tuple[str, int], CanonicalOfferGroup] = {}
    for product in products:
        key = (product.source, product.shop_id)
        group = groups.get(key)
        if group is None:
            group = CanonicalOfferGroup(
                source=product.source,
                shop_id=product.shop_id,
                shop_source_id=product.shop_source_id,
                shop_name=product.shop_name,
                items=[],
            )
            groups[key] = group
        group.items.append(product)

    return list(groups.values())


def _source_url(raw: JsonObject | None) -> str | None:
    if raw is None:
        return None

    for key in ("product_url", "url", "canonical_url"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return value

    return None
