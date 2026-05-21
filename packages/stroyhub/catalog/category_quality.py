from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from stroyhub.models import Shop, SourceProduct


@dataclass(frozen=True, kw_only=True)
class CategoryQualityFilters:
    source: str | None = None
    shop_id: int | None = None
    limit_groups: int = 50
    titles_per_group: int = 3


@dataclass(frozen=True, kw_only=True)
class UncategorizedCategoryGroup:
    source: str
    shop_id: int
    shop_name: str
    shop_source_id: str
    category_raw: str | None
    count: int
    titles: tuple[str, ...]


@dataclass(frozen=True, kw_only=True)
class CategoryQuality:
    total_products: int
    categorized_products: int
    uncategorized_products: int
    coverage_pct: Decimal
    groups: list[UncategorizedCategoryGroup]


@dataclass(frozen=True, kw_only=True)
class _ProductRow:
    source: str
    shop_id: int
    shop_name: str
    shop_source_id: str
    category_raw: str | None
    title: str
    category_id: int | None


class CategoryQualityCatalog:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_quality(self, filters: CategoryQualityFilters) -> CategoryQuality:
        products = self._list_active_products(filters)
        categorized_products = sum(1 for product in products if product.category_id is not None)
        uncategorized_products = len(products) - categorized_products

        groups = self._group_uncategorized(
            [product for product in products if product.category_id is None],
            titles_per_group=filters.titles_per_group,
        )
        if filters.limit_groups > 0:
            groups = groups[: filters.limit_groups]

        return CategoryQuality(
            total_products=len(products),
            categorized_products=categorized_products,
            uncategorized_products=uncategorized_products,
            coverage_pct=_coverage_pct(categorized_products, len(products)),
            groups=groups,
        )

    def _list_active_products(self, filters: CategoryQualityFilters) -> list[_ProductRow]:
        statement = (
            select(SourceProduct, Shop)
            .join(Shop, SourceProduct.shop_id == Shop.id)
            .where(SourceProduct.is_active.is_(True))
            .order_by(Shop.name.asc(), SourceProduct.category_raw.asc(), SourceProduct.title.asc())
        )
        if filters.source is not None:
            source = filters.source.strip()
            if source:
                statement = statement.where(SourceProduct.source == source)
        if filters.shop_id is not None:
            statement = statement.where(SourceProduct.shop_id == filters.shop_id)

        return [
            _ProductRow(
                source=product.source,
                shop_id=shop.id,
                shop_name=shop.name,
                shop_source_id=shop.source_id,
                category_raw=product.category_raw,
                title=product.title,
                category_id=product.category_id,
            )
            for product, shop in self._session.execute(statement)
        ]

    def _group_uncategorized(
        self,
        products: list[_ProductRow],
        *,
        titles_per_group: int,
    ) -> list[UncategorizedCategoryGroup]:
        grouped: dict[tuple[str, int, str | None], list[_ProductRow]] = {}
        for product in products:
            key = (product.source, product.shop_id, product.category_raw)
            grouped.setdefault(key, []).append(product)

        groups = [
            UncategorizedCategoryGroup(
                source=items[0].source,
                shop_id=items[0].shop_id,
                shop_name=items[0].shop_name,
                shop_source_id=items[0].shop_source_id,
                category_raw=items[0].category_raw,
                count=len(items),
                titles=tuple(product.title for product in items[: max(titles_per_group, 0)]),
            )
            for items in grouped.values()
        ]
        return sorted(
            groups,
            key=lambda group: (-group.count, group.shop_name, group.category_raw or ""),
        )


def _coverage_pct(categorized_products: int, total_products: int) -> Decimal:
    if total_products == 0:
        return Decimal("0.00")
    return (Decimal(categorized_products) * Decimal("100") / Decimal(total_products)).quantize(
        Decimal("0.01")
    )
