from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import false, func, or_, select
from sqlalchemy.orm import Session

from stroyhub.models.tables import CanonicalProduct, Category, ProductMatch, Shop, SourceProduct
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
    source: str
    source_product_id: str | None
    title: str
    normalized_title: str
    shop_id: int
    shop_name: str
    category_raw: str | None
    unit_raw: str | None


@dataclass(frozen=True, kw_only=True)
class CanonicalProductDetail(CanonicalProductItem):
    accepted_source_products: list[CanonicalLinkedSourceProduct]


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
        return CanonicalProductDetail(
            **item.__dict__,
            accepted_source_products=self._accepted_source_products(product.id),
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
                pattern = f"%{_escape_like_pattern(query)}%"
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

    def _accepted_source_products(
        self,
        canonical_product_id: int,
    ) -> list[CanonicalLinkedSourceProduct]:
        statement = (
            select(SourceProduct, Shop)
            .join(ProductMatch, ProductMatch.source_product_id == SourceProduct.id)
            .join(Shop, SourceProduct.shop_id == Shop.id)
            .where(
                ProductMatch.canonical_product_id == canonical_product_id,
                ProductMatch.status == "accepted",
            )
            .order_by(Shop.name.asc(), SourceProduct.normalized_title.asc(), SourceProduct.id.asc())
        )
        return [
            CanonicalLinkedSourceProduct(
                id=product.id,
                source=product.source,
                source_product_id=product.source_product_id,
                title=product.title,
                normalized_title=product.normalized_title,
                shop_id=shop.id,
                shop_name=shop.name,
                category_raw=product.category_raw,
                unit_raw=product.unit_raw,
            )
            for product, shop in self._session.execute(statement)
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


def _escape_like_pattern(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
