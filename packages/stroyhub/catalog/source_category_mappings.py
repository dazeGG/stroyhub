from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stroyhub.catalog.categorization import (
    DEFAULT_NON_PRODUCT_SOURCE_CATEGORIES,
    DEFAULT_SOURCE_CATEGORY_ALIASES,
    NonProductSourceCategory,
    RuleBasedCategorizer,
    SourceCategoryAlias,
)
from stroyhub.catalog.query_helpers import escape_like_pattern
from stroyhub.catalog.taxonomy import get_normalized_category
from stroyhub.db.repositories import SourceCategoryMappingRepository
from stroyhub.models import Category, SourceCategoryMapping, SourceProduct
from stroyhub.parsers.common import normalize_title

SourceCategoryMappingOrigin = Literal[
    "manual",
    "default_alias",
    "default_non_product",
    "unmapped",
]


@dataclass(frozen=True, kw_only=True)
class SourceCategoryMappingFilters:
    source: str | None = None
    q: str | None = None
    status: str | None = None
    limit: int = 50
    offset: int = 0
    examples_per_group: int = 3


@dataclass(frozen=True, kw_only=True)
class SourceCategoryMappingCategory:
    id: int | None
    slug: str | None
    name: str | None


@dataclass(frozen=True, kw_only=True)
class SourceCategoryMappingItem:
    source: str
    raw_category: str | None
    normalized_raw_category: str
    product_count: int
    categorized_product_count: int
    uncategorized_product_count: int
    mapping_id: int | None
    mapping_origin: SourceCategoryMappingOrigin
    mapping_status: str
    category: SourceCategoryMappingCategory | None
    confidence: Decimal | None
    reason: str | None
    examples: tuple[str, ...]


@dataclass(frozen=True, kw_only=True)
class SourceCategoryMappingPage:
    items: list[SourceCategoryMappingItem]
    limit: int
    offset: int
    total: int


class SourceCategoryMappingCatalog:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_mappings(
        self,
        filters: SourceCategoryMappingFilters,
    ) -> SourceCategoryMappingPage:
        groups = self._raw_category_groups(filters)
        manual_mappings = self._manual_mappings(filters.source)
        categories_by_slug = self._categories_by_slug()
        items = [
            self._item(
                group,
                manual_mappings=manual_mappings,
                categories_by_slug=categories_by_slug,
                examples_per_group=filters.examples_per_group,
            )
            for group in groups
        ]
        if filters.status is not None:
            selected_status = filters.status.strip()
            if selected_status:
                items = [
                    item for item in items if item.mapping_status == selected_status
                ]

        total = len(items)
        page_items = items[filters.offset : filters.offset + filters.limit]
        return SourceCategoryMappingPage(
            items=page_items,
            limit=filters.limit,
            offset=filters.offset,
            total=total,
        )

    def _raw_category_groups(
        self,
        filters: SourceCategoryMappingFilters,
    ) -> list[tuple[str, str | None, int, int]]:
        categorized_count = func.count(SourceProduct.category_id)
        statement = (
            select(
                SourceProduct.source,
                SourceProduct.category_raw,
                func.count(SourceProduct.id),
                categorized_count,
            )
            .where(SourceProduct.is_active.is_(True))
            .group_by(SourceProduct.source, SourceProduct.category_raw)
            .order_by(
                func.count(SourceProduct.id).desc(),
                SourceProduct.source.asc(),
                func.coalesce(SourceProduct.category_raw, "").asc(),
            )
        )
        if filters.source is not None:
            source = filters.source.strip()
            if source:
                statement = statement.where(SourceProduct.source == source)
        if filters.q is not None:
            query = filters.q.strip()
            if query:
                pattern = f"%{escape_like_pattern(query)}%"
                statement = statement.where(
                    SourceProduct.category_raw.ilike(pattern, escape="\\")
                )

        return [
            (source, raw_category, int(product_count), int(categorized))
            for source, raw_category, product_count, categorized in self._session.execute(
                statement
            )
        ]

    def _manual_mappings(
        self,
        source: str | None,
    ) -> dict[tuple[str, str], SourceCategoryMapping]:
        return {
            (mapping.source, mapping.normalized_raw_category): mapping
            for mapping in SourceCategoryMappingRepository(self._session).list_all(
                source=source
            )
        }

    def _categories_by_slug(self) -> dict[str, Category]:
        return {
            category.slug: category
            for category in self._session.scalars(select(Category))
        }

    def _item(
        self,
        group: tuple[str, str | None, int, int],
        *,
        manual_mappings: dict[tuple[str, str], SourceCategoryMapping],
        categories_by_slug: dict[str, Category],
        examples_per_group: int,
    ) -> SourceCategoryMappingItem:
        source, raw_category, product_count, categorized_product_count = group
        normalized_raw_category = normalize_title(raw_category or "")
        manual_mapping = manual_mappings.get((source, normalized_raw_category))
        origin: SourceCategoryMappingOrigin = "unmapped"
        status = "unmapped"
        category: SourceCategoryMappingCategory | None = None
        confidence: Decimal | None = None
        reason: str | None = None
        mapping_id: int | None = None

        if manual_mapping is not None:
            origin = "manual"
            status = manual_mapping.status
            confidence = manual_mapping.confidence
            reason = manual_mapping.reason
            mapping_id = manual_mapping.id
            if manual_mapping.category is not None:
                category = _category(manual_mapping.category)
        else:
            default_alias = _default_alias(source=source, raw_category=raw_category)
            default_non_product = _default_non_product(
                source=source,
                raw_category=raw_category,
            )
            if default_alias is not None:
                origin = "default_alias"
                status = "active"
                confidence = Decimal("0.980")
                db_category = categories_by_slug.get(default_alias.category_slug)
                taxonomy_category = get_normalized_category(default_alias.category_slug)
                category = SourceCategoryMappingCategory(
                    id=db_category.id if db_category is not None else None,
                    slug=default_alias.category_slug,
                    name=(
                        db_category.name
                        if db_category is not None
                        else taxonomy_category.name if taxonomy_category is not None else None
                    ),
                )
                reason = "default_source_category_alias"
            elif default_non_product:
                origin = "default_non_product"
                status = "non_product"
                confidence = Decimal("1.000")
                reason = "default_non_product_source_category"
            elif raw_category is None or not normalized_raw_category:
                status = "noisy"

        return SourceCategoryMappingItem(
            source=source,
            raw_category=raw_category,
            normalized_raw_category=normalized_raw_category,
            product_count=product_count,
            categorized_product_count=categorized_product_count,
            uncategorized_product_count=product_count - categorized_product_count,
            mapping_id=mapping_id,
            mapping_origin=origin,
            mapping_status=status,
            category=category,
            confidence=confidence,
            reason=reason,
            examples=self._examples(
                source=source,
                raw_category=raw_category,
                limit=examples_per_group,
            ),
        )

    def _examples(
        self,
        *,
        source: str,
        raw_category: str | None,
        limit: int,
    ) -> tuple[str, ...]:
        if limit <= 0:
            return ()

        statement = (
            select(SourceProduct.title)
            .where(
                SourceProduct.is_active.is_(True),
                SourceProduct.source == source,
            )
            .order_by(SourceProduct.title.asc(), SourceProduct.id.asc())
            .limit(limit)
        )
        if raw_category is None:
            statement = statement.where(SourceProduct.category_raw.is_(None))
        else:
            statement = statement.where(SourceProduct.category_raw == raw_category)

        return tuple(self._session.scalars(statement))


def categorizer_for_session(session: Session) -> RuleBasedCategorizer:
    mappings = SourceCategoryMappingRepository(session).list_all()
    overridden_keys = {
        (mapping.source, mapping.normalized_raw_category) for mapping in mappings
    }
    aliases = [
        alias
        for alias in DEFAULT_SOURCE_CATEGORY_ALIASES
        if (_normalize_source(alias.source), normalize_title(alias.raw_category))
        not in overridden_keys
    ]
    non_product_categories = [
        category
        for category in DEFAULT_NON_PRODUCT_SOURCE_CATEGORIES
        if (_normalize_source(category.source), normalize_title(category.raw_category))
        not in overridden_keys
    ]

    categories_by_id = {
        category.id: category for category in session.scalars(select(Category))
    }
    for mapping in mappings:
        if mapping.status == "active" and mapping.category_id in categories_by_id:
            category = categories_by_id[mapping.category_id]
            parent = (
                categories_by_id.get(category.parent_id)
                if category.parent_id is not None
                else None
            )
            aliases.append(
                SourceCategoryAlias(
                    source=mapping.source,
                    raw_category=mapping.raw_category,
                    category_slug=category.slug,
                    category_name=category.name,
                    parent_slug=parent.slug if parent is not None else None,
                    parent_name=parent.name if parent is not None else None,
                )
            )
        elif mapping.status == "non_product":
            non_product_categories.append(
                NonProductSourceCategory(
                    source=mapping.source,
                    raw_category=mapping.raw_category,
                )
            )

    return RuleBasedCategorizer(
        source_category_aliases=tuple(aliases),
        non_product_source_categories=tuple(non_product_categories),
    )


def _category(category: Category) -> SourceCategoryMappingCategory:
    return SourceCategoryMappingCategory(
        id=category.id,
        slug=category.slug,
        name=category.name,
    )


def _default_alias(
    *,
    source: str,
    raw_category: str | None,
) -> SourceCategoryAlias | None:
    if raw_category is None:
        return None

    key = (_normalize_source(source), normalize_title(raw_category))
    for alias in DEFAULT_SOURCE_CATEGORY_ALIASES:
        if (_normalize_source(alias.source), normalize_title(alias.raw_category)) == key:
            return alias
    return None


def _default_non_product(
    *,
    source: str,
    raw_category: str | None,
) -> bool:
    if raw_category is None:
        return False

    key = (_normalize_source(source), normalize_title(raw_category))
    return any(
        (_normalize_source(category.source), normalize_title(category.raw_category)) == key
        for category in DEFAULT_NON_PRODUCT_SOURCE_CATEGORIES
    )


def _normalize_source(source: str) -> str:
    return source.strip().lower()
