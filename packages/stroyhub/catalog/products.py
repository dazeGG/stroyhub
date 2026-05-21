from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import and_, false, func, or_, select
from sqlalchemy.orm import Session

from stroyhub.models.tables import Category, PriceSnapshot, Shop, SourceProduct

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


def _escape_like_pattern(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@dataclass(frozen=True, kw_only=True)
class ProductSearchFilters:
    q: str | None = None
    category_id: int | None = None
    category_slug: str | None = None
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
    currency: str
    unit_raw: str | None
    source_updated_at: datetime | None
    parsed_at: datetime


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


@dataclass(frozen=True, kw_only=True)
class ProductPriceSnapshot:
    id: int
    price: Decimal | None
    currency: str
    unit_raw: str | None
    source_updated_at: datetime | None
    parsed_at: datetime


class ProductCatalog:
    def __init__(self, session: Session) -> None:
        self._session = session

    def search_products(self, filters: ProductSearchFilters) -> list[ProductSearchItem]:
        statement, latest_prices = self._product_listing_statement()

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

        category_ids = self._category_filter_ids(filters)
        if category_ids is not None:
            if category_ids:
                statement = statement.where(SourceProduct.category_id.in_(category_ids))
            else:
                statement = statement.where(false())

        if filters.shop_id is not None:
            statement = statement.where(SourceProduct.shop_id == filters.shop_id)

        statement = (
            statement.order_by(*self._sort_expressions(filters.sort, latest_prices))
            .limit(filters.limit)
            .offset(filters.offset)
        )

        return [self._product_search_item(*row) for row in self._session.execute(statement)]

    def get_product(self, product_id: int) -> ProductSearchItem | None:
        statement, _latest_prices = self._product_listing_statement()
        row = self._session.execute(
            statement.where(SourceProduct.id == product_id)
        ).first()
        if row is None:
            return None

        return self._product_search_item(*row)

    def source_product_exists(self, product_id: int) -> bool:
        statement = select(SourceProduct.id).where(SourceProduct.id == product_id)
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
                currency=snapshot.currency,
                unit_raw=snapshot.unit_raw,
                source_updated_at=snapshot.source_updated_at,
                parsed_at=snapshot.parsed_at,
            )
            for snapshot in self._session.scalars(statement)
        ]

    def _product_listing_statement(self) -> tuple[Any, Any]:
        latest_prices = (
            select(
                PriceSnapshot.source_product_id.label("source_product_id"),
                PriceSnapshot.price.label("latest_price"),
                PriceSnapshot.currency.label("latest_currency"),
                PriceSnapshot.unit_raw.label("latest_unit_raw"),
                PriceSnapshot.source_updated_at.label("latest_source_updated_at"),
                PriceSnapshot.parsed_at.label("latest_parsed_at"),
                func.row_number()
                .over(
                    partition_by=PriceSnapshot.source_product_id,
                    order_by=(PriceSnapshot.parsed_at.desc(), PriceSnapshot.id.desc()),
                )
                .label("row_number"),
            )
            .subquery()
        )

        statement = (
            select(
                SourceProduct,
                Shop,
                latest_prices.c.latest_price,
                latest_prices.c.latest_currency,
                latest_prices.c.latest_unit_raw,
                latest_prices.c.latest_source_updated_at,
                latest_prices.c.latest_parsed_at,
            )
            .join(Shop, SourceProduct.shop_id == Shop.id)
            .outerjoin(
                latest_prices,
                and_(
                    latest_prices.c.source_product_id == SourceProduct.id,
                    latest_prices.c.row_number == 1,
                ),
            )
            .where(SourceProduct.is_active.is_(True))
        )

        return statement, latest_prices

    def _product_search_item(
        self,
        product: SourceProduct,
        shop: Shop,
        latest_price: Decimal | None,
        latest_currency: str | None,
        latest_unit_raw: str | None,
        latest_source_updated_at: datetime | None,
        latest_parsed_at: datetime | None,
    ) -> ProductSearchItem:
        price = None
        if latest_parsed_at is not None:
            price = ProductLatestPrice(
                price=latest_price,
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

        category_rows = self._session.execute(select(Category.id, Category.parent_id))
        child_ids_by_parent: dict[int, list[int]] = {}
        known_ids: set[int] = set()
        for category_id, parent_id in category_rows:
            known_ids.add(category_id)
            if parent_id is not None:
                child_ids_by_parent.setdefault(parent_id, []).append(category_id)

        category_ids = {category_id for category_id in starting_ids if category_id in known_ids}
        pending = list(category_ids)
        while pending:
            category_id = pending.pop()
            for child_id in child_ids_by_parent.get(category_id, []):
                if child_id not in category_ids:
                    category_ids.add(child_id)
                    pending.append(child_id)

        return category_ids

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
