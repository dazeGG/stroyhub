from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from stroyhub.catalog.categorization import RuleBasedCategorizer
from stroyhub.ml.labels import CategoryLabelStore
from stroyhub.models import Category, SourceProduct


@dataclass(frozen=True, kw_only=True)
class CategoryLabelCandidate:
    id: int
    slug: str
    name: str
    parent_id: int | None
    reason: str


@dataclass(frozen=True, kw_only=True)
class CategoryLabelProduct:
    id: int
    source: str
    title: str
    normalized_title: str
    category_id: int | None
    category_raw: str | None


@dataclass(frozen=True, kw_only=True)
class CategoryLabelQueueItem:
    product: CategoryLabelProduct
    candidates: tuple[CategoryLabelCandidate, ...]


class CategoryLabelQueue:
    def __init__(
        self,
        session: Session,
        label_store: CategoryLabelStore,
        *,
        candidate_count: int = 3,
        source: str | None = None,
    ) -> None:
        self._session = session
        self._label_store = label_store
        self._candidate_count = candidate_count
        self._source = source
        self._categorizer = RuleBasedCategorizer()

    def next_item(
        self,
        *,
        excluded_product_ids: set[int] | None = None,
    ) -> CategoryLabelQueueItem | None:
        categories = self._leaf_categories()
        if len(categories) < self._candidate_count:
            return None

        excluded_product_ids = excluded_product_ids or set()
        labeled_pairs = self._label_store.labeled_pairs()
        products = self._products()
        for product in products:
            if product.id in excluded_product_ids:
                continue
            candidates = self._candidates_for_product(product, categories, labeled_pairs)
            if len(candidates) == self._candidate_count:
                return CategoryLabelQueueItem(
                    product=CategoryLabelProduct(
                        id=product.id,
                        source=product.source,
                        title=product.title,
                        normalized_title=product.normalized_title,
                        category_id=product.category_id,
                        category_raw=product.category_raw,
                    ),
                    candidates=tuple(candidates),
                )

        return None

    def _products(self) -> list[SourceProduct]:
        statement = (
            select(SourceProduct)
            .where(SourceProduct.is_active.is_(True))
            .order_by(SourceProduct.id.asc())
        )
        if self._source is not None:
            statement = statement.where(SourceProduct.source == self._source)
        return list(self._session.scalars(statement))

    def _leaf_categories(self) -> list[Category]:
        child_parent_ids = {
            parent_id
            for (parent_id,) in self._session.execute(
                select(Category.parent_id).where(Category.parent_id.is_not(None))
            )
            if parent_id is not None
        }
        statement = select(Category).order_by(Category.id.asc())
        return [
            category
            for category in self._session.scalars(statement)
            if category.id not in child_parent_ids
        ]

    def _candidates_for_product(
        self,
        product: SourceProduct,
        categories: list[Category],
        labeled_pairs: set[tuple[int, int]],
    ) -> list[CategoryLabelCandidate]:
        category_by_id = {category.id: category for category in categories}
        category_by_slug = {category.slug: category for category in categories}
        selected: list[CategoryLabelCandidate] = []
        selected_ids: set[int] = set()

        def add(category: Category | None, reason: str) -> None:
            if category is None:
                return
            if category.id in selected_ids:
                return
            if (product.id, category.id) in labeled_pairs:
                return
            selected.append(_candidate(category, reason))
            selected_ids.add(category.id)

        add(category_by_id.get(product.category_id or 0), "current_category")

        prediction = self._categorizer.categorize(
            title=product.title,
            source=product.source,
            category_raw=product.category_raw,
            description=product.description,
        )
        if prediction is not None:
            add(category_by_slug.get(prediction.category_slug), "rule_prediction")

        signal_text = _signal_text(product)
        for category in categories:
            if _matches_signal(category, signal_text):
                add(category, "text_signal")

        anchor_parent_ids = {
            candidate.parent_id
            for candidate in selected
            if candidate.parent_id is not None
        }
        for category in categories:
            if category.parent_id in anchor_parent_ids:
                add(category, "nearby_category")

        for category in categories:
            add(category, "fallback")
            if len(selected) >= self._candidate_count:
                break

        return selected[: self._candidate_count]


def _candidate(category: Category, reason: str) -> CategoryLabelCandidate:
    return CategoryLabelCandidate(
        id=category.id,
        slug=category.slug,
        name=category.name,
        parent_id=category.parent_id,
        reason=reason,
    )


def _signal_text(product: SourceProduct) -> str:
    return " ".join(
        value.lower()
        for value in (
            product.title,
            product.normalized_title,
            product.category_raw,
        )
        if value
    )


def _matches_signal(category: Category, signal_text: str) -> bool:
    values = {category.slug.replace("_", " ").lower(), category.name.lower()}
    return any(value and value in signal_text for value in values)
