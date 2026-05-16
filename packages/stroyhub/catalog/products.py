from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from stroyhub.models.tables import PriceSnapshot, Shop, SourceProduct


def _escape_like_pattern(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@dataclass(frozen=True, kw_only=True)
class ProductSearchFilters:
    q: str | None = None
    category_id: int | None = None
    shop_id: int | None = None
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


class ProductCatalog:
    def __init__(self, session: Session) -> None:
        self._session = session

    def search_products(self, filters: ProductSearchFilters) -> list[ProductSearchItem]:
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
            .order_by(SourceProduct.last_seen_at.desc(), SourceProduct.id.asc())
            .limit(filters.limit)
            .offset(filters.offset)
        )

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

        if filters.category_id is not None:
            statement = statement.where(SourceProduct.category_id == filters.category_id)

        if filters.shop_id is not None:
            statement = statement.where(SourceProduct.shop_id == filters.shop_id)

        items: list[ProductSearchItem] = []
        for (
            product,
            shop,
            latest_price,
            latest_currency,
            latest_unit_raw,
            latest_source_updated_at,
            latest_parsed_at,
        ) in self._session.execute(statement):
            price = None
            if latest_parsed_at is not None:
                price = ProductLatestPrice(
                    price=latest_price,
                    currency=latest_currency,
                    unit_raw=latest_unit_raw,
                    source_updated_at=latest_source_updated_at,
                    parsed_at=latest_parsed_at,
                )

            items.append(
                ProductSearchItem(
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
            )

        return items
