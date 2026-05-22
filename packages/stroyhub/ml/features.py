from __future__ import annotations

from dataclasses import dataclass

from stroyhub.parsers.common import normalize_title

CATEGORY_VERIFIER_FEATURE_SCHEMA_VERSION = "category_verifier_features/v1"


@dataclass(frozen=True, kw_only=True)
class CategoryVerifierProductInput:
    source: str
    title: str
    id: int | None = None
    normalized_title: str | None = None
    category_raw: str | None = None
    shop_id: int | None = None
    category_id: int | None = None
    description: str | None = None


@dataclass(frozen=True, kw_only=True)
class CategoryVerifierCategoryInput:
    slug: str
    name: str
    id: int | None = None
    parent_id: int | None = None


@dataclass(frozen=True, kw_only=True)
class CategoryVerifierFeatureRow:
    schema_version: str
    values: dict[str, str]


def build_category_verifier_features(
    *,
    product: CategoryVerifierProductInput,
    category: CategoryVerifierCategoryInput,
    category_path: tuple[CategoryVerifierCategoryInput, ...] = (),
) -> CategoryVerifierFeatureRow:
    """Build deterministic verifier features for one product/category pair."""
    path = _normalized_category_path(category=category, category_path=category_path)
    product_title = _normalize(product.title)
    product_normalized_title = _normalize(product.normalized_title or product.title)
    product_category_raw = _normalize(product.category_raw)
    product_description = _normalize(product.description)
    product_source = _normalize(product.source)
    category_name = _normalize(category.name)
    category_slug_text = _normalize(category.slug.replace("_", " "))
    category_path_names = " ".join(_normalize(item.name) for item in path)
    category_path_slugs = " ".join(_normalize(item.slug.replace("_", " ")) for item in path)

    product_context_text = _join_text(
        product_title,
        product_normalized_title,
        product_category_raw,
        product_description,
        product_source,
    )
    category_context_text = _join_text(
        category_name,
        category_slug_text,
        category_path_names,
        category_path_slugs,
    )

    return CategoryVerifierFeatureRow(
        schema_version=CATEGORY_VERIFIER_FEATURE_SCHEMA_VERSION,
        values={
            "product.source": product_source,
            "product.shop_id": "" if product.shop_id is None else str(product.shop_id),
            "product.title": product_title,
            "product.normalized_title": product_normalized_title,
            "product.category_raw": product_category_raw,
            "product.description": product_description,
            "product.context_text": product_context_text,
            "category.id": "" if category.id is None else str(category.id),
            "category.slug": _normalize(category.slug),
            "category.slug_text": category_slug_text,
            "category.name": category_name,
            "category.parent_id": "" if category.parent_id is None else str(category.parent_id),
            "category.path_names": category_path_names,
            "category.path_slugs": category_path_slugs,
            "category.context_text": category_context_text,
            "pair.context_text": _join_text(product_context_text, category_context_text),
            "pair.product_has_current_category": _bool_feature(
                product.category_id is not None
                and category.id is not None
                and product.category_id == category.id
            ),
            "pair.raw_category_mentions_category": _bool_feature(
                _contains_text(product_category_raw, category_name)
                or _contains_text(product_category_raw, category_slug_text)
            ),
            "pair.title_mentions_category": _bool_feature(
                _contains_text(product_normalized_title, category_name)
                or _contains_text(product_normalized_title, category_slug_text)
            ),
        },
    )


def _normalized_category_path(
    *,
    category: CategoryVerifierCategoryInput,
    category_path: tuple[CategoryVerifierCategoryInput, ...],
) -> tuple[CategoryVerifierCategoryInput, ...]:
    if not category_path:
        return (category,)
    if category_path[-1] == category:
        return category_path
    return (*category_path, category)


def _normalize(value: str | None) -> str:
    if value is None:
        return ""
    return normalize_title(value)


def _join_text(*parts: str) -> str:
    return " ".join(part for part in parts if part)


def _bool_feature(value: bool) -> str:
    return "1" if value else "0"


def _contains_text(haystack: str, needle: str) -> bool:
    return bool(haystack and needle and needle in haystack)
