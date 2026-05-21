from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from stroyhub.models.tables import Category, PriceSnapshot, Shop, SourceProduct

MONEY_QUANT = Decimal("0.01")


@dataclass(kw_only=True)
class CategoryTreeItem:
    id: int
    slug: str
    name: str
    parent_id: int | None
    product_count: int
    children: list["CategoryTreeItem"] = field(default_factory=list)


@dataclass(frozen=True, kw_only=True)
class CategoryPriceSummaryFilters:
    source: str | None = None
    shop_id: int | None = None


@dataclass(frozen=True, kw_only=True)
class CategoryPriceSummaryItem:
    category_id: int | None
    category_slug: str | None
    category_name: str | None
    product_count: int
    priced_product_count: int
    min_price: Decimal | None
    avg_price: Decimal | None
    max_price: Decimal | None


class CategoryCatalog:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_tree(self) -> list[CategoryTreeItem]:
        categories = list(
            self._session.scalars(
                select(Category).order_by(
                    Category.parent_id.asc().nullsfirst(),
                    Category.name.asc(),
                    Category.id.asc(),
                )
            )
        )
        if not categories:
            return []

        direct_counts: dict[int, int] = {}
        count_rows = self._session.execute(
            select(SourceProduct.category_id, func.count(SourceProduct.id))
            .where(
                SourceProduct.is_active.is_(True),
                SourceProduct.category_id.is_not(None),
            )
            .group_by(SourceProduct.category_id)
        )
        for category_id, product_count in count_rows:
            if category_id is not None:
                direct_counts[category_id] = product_count

        items_by_id = {
            category.id: CategoryTreeItem(
                id=category.id,
                slug=category.slug,
                name=category.name,
                parent_id=category.parent_id,
                product_count=int(direct_counts.get(category.id, 0)),
            )
            for category in categories
        }

        roots: list[CategoryTreeItem] = []
        for category in categories:
            item = items_by_id[category.id]
            if category.parent_id is None:
                roots.append(item)
                continue

            parent = items_by_id.get(category.parent_id)
            if parent is None:
                roots.append(item)
            else:
                parent.children.append(item)

        for root in roots:
            self._roll_up_product_count(root)

        return roots

    def list_price_summary(
        self, filters: CategoryPriceSummaryFilters
    ) -> list[CategoryPriceSummaryItem]:
        latest_prices = (
            select(
                PriceSnapshot.source_product_id.label("source_product_id"),
                PriceSnapshot.price.label("latest_price"),
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
                SourceProduct.category_id,
                Category.slug,
                Category.name,
                func.count(SourceProduct.id),
                func.count(latest_prices.c.latest_price),
                func.min(latest_prices.c.latest_price),
                func.avg(latest_prices.c.latest_price),
                func.max(latest_prices.c.latest_price),
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
            .group_by(SourceProduct.category_id, Category.slug, Category.name)
            .order_by(Category.name.asc().nullslast(), SourceProduct.category_id.asc().nullslast())
        )

        if filters.source is not None:
            source = filters.source.strip()
            if source:
                statement = statement.where(SourceProduct.source == source)

        if filters.shop_id is not None:
            statement = statement.where(SourceProduct.shop_id == filters.shop_id)

        return [
            CategoryPriceSummaryItem(
                category_id=category_id,
                category_slug=category_slug,
                category_name=category_name,
                product_count=product_count,
                priced_product_count=priced_product_count,
                min_price=_quantize_money(min_price),
                avg_price=_quantize_money(avg_price),
                max_price=_quantize_money(max_price),
            )
            for (
                category_id,
                category_slug,
                category_name,
                product_count,
                priced_product_count,
                min_price,
                avg_price,
                max_price,
            ) in self._session.execute(statement)
        ]

    def _roll_up_product_count(self, item: CategoryTreeItem) -> int:
        item.product_count += sum(
            self._roll_up_product_count(child) for child in item.children
        )
        return item.product_count


def _quantize_money(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return value.quantize(MONEY_QUANT)
