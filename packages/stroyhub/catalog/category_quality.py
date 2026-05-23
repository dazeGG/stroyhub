from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
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


class CategoryQualityCatalog:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_quality(self, filters: CategoryQualityFilters) -> CategoryQuality:
        total_products, categorized_products = self._count_products(filters)
        uncategorized_products = total_products - categorized_products
        groups = self._list_uncategorized_groups(filters)

        return CategoryQuality(
            total_products=total_products,
            categorized_products=categorized_products,
            uncategorized_products=uncategorized_products,
            coverage_pct=_coverage_pct(categorized_products, total_products),
            groups=groups,
        )

    def _count_products(self, filters: CategoryQualityFilters) -> tuple[int, int]:
        statement = (
            select(func.count(SourceProduct.id), func.count(SourceProduct.category_id))
            .where(SourceProduct.is_active.is_(True))
        )
        if filters.source is not None:
            source = filters.source.strip()
            if source:
                statement = statement.where(SourceProduct.source == source)
        if filters.shop_id is not None:
            statement = statement.where(SourceProduct.shop_id == filters.shop_id)

        total_products, categorized_products = self._session.execute(statement).one()
        return int(total_products or 0), int(categorized_products or 0)

    def _list_uncategorized_groups(
        self, filters: CategoryQualityFilters
    ) -> list[UncategorizedCategoryGroup]:
        count_expr = func.count(SourceProduct.id)
        statement = (
            select(
                SourceProduct.source,
                Shop.id,
                Shop.name,
                Shop.source_id,
                SourceProduct.category_raw,
                count_expr,
            )
            .join(Shop, SourceProduct.shop_id == Shop.id)
            .where(SourceProduct.is_active.is_(True), SourceProduct.category_id.is_(None))
            .group_by(
                SourceProduct.source,
                Shop.id,
                Shop.name,
                Shop.source_id,
                SourceProduct.category_raw,
            )
            .order_by(
                count_expr.desc(),
                Shop.name.asc(),
                func.coalesce(SourceProduct.category_raw, "").asc(),
            )
        )
        if filters.source is not None:
            source = filters.source.strip()
            if source:
                statement = statement.where(SourceProduct.source == source)
        if filters.shop_id is not None:
            statement = statement.where(SourceProduct.shop_id == filters.shop_id)
        if filters.limit_groups > 0:
            statement = statement.limit(filters.limit_groups)

        return [
            UncategorizedCategoryGroup(
                source=source,
                shop_id=shop_id,
                shop_name=shop_name,
                shop_source_id=shop_source_id,
                category_raw=category_raw,
                count=int(product_count),
                titles=self._list_uncategorized_titles(
                    source=source,
                    shop_id=shop_id,
                    category_raw=category_raw,
                    limit=filters.titles_per_group,
                ),
            )
            for (
                source,
                shop_id,
                shop_name,
                shop_source_id,
                category_raw,
                product_count,
            ) in self._session.execute(statement)
        ]

    def _list_uncategorized_titles(
        self,
        *,
        source: str,
        shop_id: int,
        category_raw: str | None,
        limit: int,
    ) -> tuple[str, ...]:
        if limit <= 0:
            return ()

        statement = (
            select(SourceProduct.title)
            .where(
                SourceProduct.is_active.is_(True),
                SourceProduct.category_id.is_(None),
                SourceProduct.source == source,
                SourceProduct.shop_id == shop_id,
            )
            .order_by(SourceProduct.title.asc())
            .limit(limit)
        )
        if category_raw is None:
            statement = statement.where(SourceProduct.category_raw.is_(None))
        else:
            statement = statement.where(SourceProduct.category_raw == category_raw)

        return tuple(self._session.scalars(statement))


def _coverage_pct(categorized_products: int, total_products: int) -> Decimal:
    if total_products == 0:
        return Decimal("0.00")
    return (Decimal(categorized_products) * Decimal("100") / Decimal(total_products)).quantize(
        Decimal("0.01")
    )
