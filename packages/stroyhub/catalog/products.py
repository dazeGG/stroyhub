from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import and_, exists, false, func, not_, or_, select
from sqlalchemy.orm import Session, aliased

from stroyhub.catalog.query_helpers import (
    category_descendant_ids,
    escape_like_pattern,
    latest_price_subquery,
)
from stroyhub.models.tables import (
    Category,
    CategoryOverride,
    PriceSnapshot,
    Shop,
    ShopIdentity,
    SourceProduct,
)

ProductSort = Literal[
    "latest_price",
    "-latest_price",
    "title",
    "-title",
    "shop",
    "-shop",
    "last_seen_at",
    "-last_seen_at",
]

_PUBLIC_HEALTHY_SCRAPE_STATUSES = ("ok", "success", "partial")

@dataclass(frozen=True, kw_only=True)
class ProductSearchFilters:
    q: str | None = None
    category_id: int | None = None
    category_slug: str | None = None
    uncategorized: bool = False
    shop_id: int | None = None
    sort: ProductSort = "-last_seen_at"
    limit: int = 50
    offset: int = 0


@dataclass(frozen=True, kw_only=True)
class ProductShop:
    id: int
    source: str
    source_id: str
    name: str


@dataclass(frozen=True, kw_only=True)
class ProductLatestPrice:
    price: Decimal | None
    price_kind: str
    price_text: str | None
    currency: str
    unit_raw: str | None
    source_updated_at: datetime | None
    parsed_at: datetime


@dataclass(frozen=True, kw_only=True)
class ProductCategoryOverride:
    id: int
    category_id: int
    previous_category_id: int | None
    reason: str | None
    status: str
    created_by: str | None
    created_at: datetime
    updated_by: str | None
    updated_at: datetime
    deactivated_by: str | None
    deactivated_at: datetime | None


@dataclass(frozen=True, kw_only=True)
class ProductSearchItem:
    id: int
    source: str
    source_product_id: str | None
    title: str
    normalized_title: str
    description: str | None
    category_id: int | None
    category_raw: str | None
    unit_raw: str | None
    image_url: str | None
    source_updated_at: datetime | None
    last_seen_at: datetime
    shop: ProductShop
    latest_price: ProductLatestPrice | None
    category_override: ProductCategoryOverride | None


@dataclass(frozen=True, kw_only=True)
class ProductPriceSnapshot:
    id: int
    price: Decimal | None
    price_kind: str
    price_text: str | None
    currency: str
    unit_raw: str | None
    source_updated_at: datetime | None
    parsed_at: datetime


class ProductCatalog:
    def __init__(self, session: Session, *, public_visibility: bool = False) -> None:
        self._session = session
        self._public_visibility = public_visibility

    def search_products(self, filters: ProductSearchFilters) -> list[ProductSearchItem]:
        statement, latest_prices = self._product_listing_statement()
        statement = self._apply_product_filters(statement, filters)

        statement = (
            statement.order_by(*self._sort_expressions(filters.sort, latest_prices))
            .limit(filters.limit)
            .offset(filters.offset)
        )

        return [self._product_search_item(*row) for row in self._session.execute(statement)]

    def count_products(self, filters: ProductSearchFilters) -> int:
        statement = (
            select(func.count(SourceProduct.id))
            .join(Shop, SourceProduct.shop_id == Shop.id)
            .outerjoin(ShopIdentity, Shop.shop_identity_id == ShopIdentity.id)
            .where(SourceProduct.is_active.is_(True))
        )
        if self._public_visibility:
            statement = statement.where(self._public_visibility_predicate())
        statement = self._apply_product_filters(statement, filters)
        return int(self._session.scalar(statement) or 0)

    def get_product(self, product_id: int) -> ProductSearchItem | None:
        statement, _latest_prices = self._product_listing_statement()
        row = self._session.execute(
            statement.where(SourceProduct.id == product_id)
        ).first()
        if row is None:
            return None

        return self._product_search_item(*row)

    def source_product_exists(self, product_id: int) -> bool:
        statement = (
            select(SourceProduct.id)
            .join(Shop, SourceProduct.shop_id == Shop.id)
            .outerjoin(ShopIdentity, Shop.shop_identity_id == ShopIdentity.id)
            .where(SourceProduct.id == product_id)
            .where(SourceProduct.is_active.is_(True))
        )
        if self._public_visibility:
            statement = statement.where(self._public_visibility_predicate())
        return self._session.scalar(statement) is not None

    def list_price_history(self, product_id: int) -> list[ProductPriceSnapshot]:
        statement = (
            select(PriceSnapshot)
            .where(PriceSnapshot.source_product_id == product_id)
            .order_by(PriceSnapshot.parsed_at.asc(), PriceSnapshot.id.asc())
        )

        return [
            ProductPriceSnapshot(
                id=snapshot.id,
                price=snapshot.price,
                price_kind=snapshot.price_kind,
                price_text=format_price_text(
                    price=snapshot.price,
                    currency=snapshot.currency,
                    price_kind=snapshot.price_kind,
                ),
                currency=snapshot.currency,
                unit_raw=snapshot.unit_raw,
                source_updated_at=snapshot.source_updated_at,
                parsed_at=snapshot.parsed_at,
            )
            for snapshot in self._session.scalars(statement)
        ]

    def _product_listing_statement(self) -> tuple[Any, Any]:
        latest_prices = latest_price_subquery()

        statement = (
            select(
                SourceProduct,
                Shop,
                latest_prices.c.latest_price,
                latest_prices.c.latest_price_kind,
                latest_prices.c.latest_currency,
                latest_prices.c.latest_unit_raw,
                latest_prices.c.latest_source_updated_at,
                latest_prices.c.latest_parsed_at,
                CategoryOverride,
            )
            .join(Shop, SourceProduct.shop_id == Shop.id)
            .outerjoin(ShopIdentity, Shop.shop_identity_id == ShopIdentity.id)
            .outerjoin(
                latest_prices,
                and_(
                    latest_prices.c.source_product_id == SourceProduct.id,
                    latest_prices.c.row_number == 1,
                ),
            )
            .outerjoin(
                CategoryOverride,
                and_(
                    CategoryOverride.source_product_id == SourceProduct.id,
                    CategoryOverride.status == "active",
                ),
            )
            .where(SourceProduct.is_active.is_(True))
        )
        if self._public_visibility:
            statement = statement.where(self._public_visibility_predicate())

        return statement, latest_prices

    def _apply_product_filters(self, statement: Any, filters: ProductSearchFilters) -> Any:
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

        if filters.uncategorized:
            statement = statement.where(SourceProduct.category_id.is_(None))
        elif (category_ids := self._category_filter_ids(filters)) is not None:
            if category_ids:
                statement = statement.where(SourceProduct.category_id.in_(category_ids))
            else:
                statement = statement.where(false())

        if filters.shop_id is not None:
            statement = statement.where(SourceProduct.shop_id == filters.shop_id)

        return statement

    def _product_search_item(
        self,
        product: SourceProduct,
        shop: Shop,
        latest_price: Decimal | None,
        latest_price_kind: str | None,
        latest_currency: str | None,
        latest_unit_raw: str | None,
        latest_source_updated_at: datetime | None,
        latest_parsed_at: datetime | None,
        category_override: CategoryOverride | None,
    ) -> ProductSearchItem:
        price = None
        if latest_parsed_at is not None:
            price = ProductLatestPrice(
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

        return ProductSearchItem(
            id=product.id,
            source=product.source,
            source_product_id=product.source_product_id,
            title=product.title,
            normalized_title=product.normalized_title,
            description=product.description,
            category_id=product.category_id,
            category_raw=product.category_raw,
            unit_raw=product.unit_raw,
            image_url=product.image_url,
            source_updated_at=product.source_updated_at,
            last_seen_at=product.last_seen_at,
            shop=ProductShop(
                id=shop.id,
                source=shop.source,
                source_id=shop.source_id,
                name=shop.name,
            ),
            latest_price=price,
            category_override=self._category_override_info(category_override),
        )

    def _category_override_info(
        self, category_override: CategoryOverride | None
    ) -> ProductCategoryOverride | None:
        if category_override is None:
            return None

        return ProductCategoryOverride(
            id=category_override.id,
            category_id=category_override.category_id,
            previous_category_id=category_override.previous_category_id,
            reason=category_override.reason,
            status=category_override.status,
            created_by=category_override.created_by,
            created_at=category_override.created_at,
            updated_by=category_override.updated_by,
            updated_at=category_override.updated_at,
            deactivated_by=category_override.deactivated_by,
            deactivated_at=category_override.deactivated_at,
        )

    def _category_filter_ids(self, filters: ProductSearchFilters) -> set[int] | None:
        starting_ids: set[int] = set()
        if filters.category_id is not None:
            starting_ids.add(filters.category_id)

        if filters.category_slug is not None:
            slug = filters.category_slug.strip()
            if slug:
                starting_ids.update(
                    self._session.scalars(select(Category.id).where(Category.slug == slug))
                )

        if not starting_ids:
            return None
        return category_descendant_ids(self._session, starting_ids)

    def _sort_expressions(self, sort: ProductSort, latest_prices: Any) -> tuple[Any, ...]:
        if sort == "latest_price":
            return (latest_prices.c.latest_price.asc().nullslast(), SourceProduct.id.asc())
        if sort == "-latest_price":
            return (latest_prices.c.latest_price.desc().nullslast(), SourceProduct.id.asc())
        if sort == "title":
            return (SourceProduct.normalized_title.asc(), SourceProduct.id.asc())
        if sort == "-title":
            return (SourceProduct.normalized_title.desc(), SourceProduct.id.asc())
        if sort == "shop":
            return (Shop.name.asc(), SourceProduct.id.asc())
        if sort == "-shop":
            return (Shop.name.desc(), SourceProduct.id.asc())
        if sort == "last_seen_at":
            return (SourceProduct.last_seen_at.asc(), SourceProduct.id.asc())
        return (SourceProduct.last_seen_at.desc(), SourceProduct.id.asc())

    def _public_visibility_predicate(self) -> Any:
        preferred_shop = aliased(Shop)
        preferred_product = aliased(SourceProduct)
        eligibility_status = SourceProduct.raw["catalog_eligibility"]["status"].astext
        preferred_eligibility_status = preferred_product.raw["catalog_eligibility"][
            "status"
        ].astext
        preferred_source_has_products = exists(
            select(preferred_shop.id)
            .join(
                preferred_product,
                and_(
                    preferred_product.shop_id == preferred_shop.id,
                    preferred_product.is_active.is_(True),
                    preferred_product.is_not_product.is_(False),
                    preferred_eligibility_status == "eligible",
                ),
            )
            .where(
                preferred_shop.shop_identity_id == Shop.shop_identity_id,
                preferred_shop.source == ShopIdentity.preferred_source,
                preferred_shop.scrape_status.in_(_PUBLIC_HEALTHY_SCRAPE_STATUSES),
            )
        )

        return and_(
            SourceProduct.is_not_product.is_(False),
            eligibility_status == "eligible",
            Shop.scrape_status != "disabled",
            or_(
                Shop.shop_identity_id.is_(None),
                and_(
                    ShopIdentity.status == "active",
                    or_(
                        ShopIdentity.preferred_source.is_(None),
                        not_(preferred_source_has_products),
                        Shop.source == ShopIdentity.preferred_source,
                    ),
                ),
            ),
        )


def format_price_text(
    *,
    price: Decimal | None,
    currency: str,
    price_kind: str,
) -> str | None:
    if price is None:
        return None

    amount = f"{price:.2f}"
    if price_kind in {"from", "range"}:
        return f"от {amount} {currency}"
    return f"{amount} {currency}"
