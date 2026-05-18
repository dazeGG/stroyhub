#!/usr/bin/env python
import argparse
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session
from stroyhub.db import SessionLocal
from stroyhub.models import Shop, SourceProduct


@dataclass(frozen=True, kw_only=True)
class UncategorizedProduct:
    source: str
    shop_id: int
    shop_name: str
    shop_source_id: str
    category_raw: str | None
    title: str


@dataclass(frozen=True, kw_only=True)
class CategoryQualityProduct:
    source: str
    shop_id: int
    shop_name: str
    shop_source_id: str
    category_raw: str | None
    title: str
    category_id: int | None
    category_confidence: Decimal | None


@dataclass(frozen=True, kw_only=True)
class UncategorizedGroup:
    source: str
    shop_id: int
    shop_name: str
    shop_source_id: str
    category_raw: str | None
    count: int
    titles: tuple[str, ...]


@dataclass(frozen=True, kw_only=True)
class RawCategoryMetric:
    source: str
    category_raw: str | None
    count: int
    categorized_count: int
    uncategorized_count: int


@dataclass(frozen=True, kw_only=True)
class CategoryQualityMetrics:
    total_products: int
    categorized_products: int
    uncategorized_products: int
    coverage_pct: Decimal
    low_confidence_products: int
    low_confidence_threshold: Decimal
    top_raw_categories: tuple[RawCategoryMetric, ...]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Print uncategorized source product groups for taxonomy/rule updates."
    )
    parser.add_argument("--source")
    parser.add_argument("--shop-id", type=int)
    parser.add_argument("--limit-groups", type=int, default=50)
    parser.add_argument("--limit-raw-categories", type=int, default=10)
    parser.add_argument("--titles-per-group", type=int, default=3)
    parser.add_argument("--low-confidence-threshold", type=Decimal, default=Decimal("0.70"))
    args = parser.parse_args(argv)

    with SessionLocal() as session:
        products = _list_active_products(
            session,
            source=args.source,
            shop_id=args.shop_id,
        )

    metrics = calculate_quality_metrics(
        products,
        low_confidence_threshold=args.low_confidence_threshold,
        raw_category_limit=args.limit_raw_categories,
    )
    uncategorized_products = [
        UncategorizedProduct(
            source=product.source,
            shop_id=product.shop_id,
            shop_name=product.shop_name,
            shop_source_id=product.shop_source_id,
            category_raw=product.category_raw,
            title=product.title,
        )
        for product in products
        if product.category_id is None
    ]
    groups = group_uncategorized_products(
        uncategorized_products,
        titles_per_group=args.titles_per_group,
    )
    total_products = sum(group.count for group in groups)
    total_groups = len(groups)
    if args.limit_groups > 0:
        groups = groups[: args.limit_groups]

    _print_report(
        groups,
        total_products=total_products,
        total_groups=total_groups,
        metrics=metrics,
    )
    return 0


def _list_active_products(
    session: Session,
    *,
    source: str | None,
    shop_id: int | None,
) -> list[CategoryQualityProduct]:
    statement = (
        select(SourceProduct, Shop)
        .join(Shop, SourceProduct.shop_id == Shop.id)
        .where(SourceProduct.is_active.is_(True))
        .order_by(Shop.name.asc(), SourceProduct.category_raw.asc(), SourceProduct.title.asc())
    )
    if source is not None:
        statement = statement.where(SourceProduct.source == source)
    if shop_id is not None:
        statement = statement.where(SourceProduct.shop_id == shop_id)

    return [
        CategoryQualityProduct(
            source=product.source,
            shop_id=shop.id,
            shop_name=shop.name,
            shop_source_id=shop.source_id,
            category_raw=product.category_raw,
            title=product.title,
            category_id=product.category_id,
            category_confidence=_category_confidence(product.raw),
        )
        for product, shop in session.execute(statement)
    ]


def calculate_quality_metrics(
    products: Sequence[CategoryQualityProduct],
    *,
    low_confidence_threshold: Decimal,
    raw_category_limit: int,
) -> CategoryQualityMetrics:
    total_products = len(products)
    categorized_products = sum(1 for product in products if product.category_id is not None)
    uncategorized_products = total_products - categorized_products
    low_confidence_products = sum(
        1
        for product in products
        if product.category_confidence is not None
        and product.category_confidence < low_confidence_threshold
    )
    raw_categories = _top_raw_categories(products)
    if raw_category_limit > 0:
        raw_categories = raw_categories[:raw_category_limit]

    return CategoryQualityMetrics(
        total_products=total_products,
        categorized_products=categorized_products,
        uncategorized_products=uncategorized_products,
        coverage_pct=_coverage_pct(categorized_products, total_products),
        low_confidence_products=low_confidence_products,
        low_confidence_threshold=low_confidence_threshold,
        top_raw_categories=tuple(raw_categories),
    )


def _top_raw_categories(products: Sequence[CategoryQualityProduct]) -> list[RawCategoryMetric]:
    grouped: dict[tuple[str, str | None], list[CategoryQualityProduct]] = defaultdict(list)
    for product in products:
        grouped[(product.source, product.category_raw)].append(product)

    metrics = [
        RawCategoryMetric(
            source=source,
            category_raw=category_raw,
            count=len(items),
            categorized_count=sum(1 for item in items if item.category_id is not None),
            uncategorized_count=sum(1 for item in items if item.category_id is None),
        )
        for (source, category_raw), items in grouped.items()
    ]
    return sorted(
        metrics,
        key=lambda metric: (-metric.count, metric.source, metric.category_raw or ""),
    )


def group_uncategorized_products(
    products: Iterable[UncategorizedProduct],
    *,
    titles_per_group: int,
) -> list[UncategorizedGroup]:
    grouped: dict[tuple[str, int, str | None], list[UncategorizedProduct]] = defaultdict(list)
    for product in products:
        grouped[(product.source, product.shop_id, product.category_raw)].append(product)

    groups = [
        UncategorizedGroup(
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


def _print_report(
    groups: Sequence[UncategorizedGroup],
    *,
    total_products: int,
    total_groups: int,
    metrics: CategoryQualityMetrics,
) -> None:
    print(
        "category quality summary: "
        f"total_products={metrics.total_products} "
        f"categorized_products={metrics.categorized_products} "
        f"uncategorized_products={metrics.uncategorized_products} "
        f"coverage_pct={metrics.coverage_pct} "
        f"low_confidence_products={metrics.low_confidence_products} "
        f"low_confidence_threshold={metrics.low_confidence_threshold}"
    )
    for raw_category in metrics.top_raw_categories:
        print(_format_raw_category_metric(raw_category))

    print(
        "category coverage summary: "
        f"uncategorized_products={total_products} "
        f"groups={total_groups} "
        f"groups_displayed={len(groups)}"
    )
    for group in groups:
        print(_format_group(group))
        for title in group.titles:
            print(f"  title: {title}")


def _format_raw_category_metric(metric: RawCategoryMetric) -> str:
    return (
        "top raw category: "
        f"source={metric.source} "
        f"category_raw={_value(metric.category_raw)} "
        f"count={metric.count} "
        f"categorized={metric.categorized_count} "
        f"uncategorized={metric.uncategorized_count}"
    )


def _format_group(group: UncategorizedGroup) -> str:
    return (
        "uncategorized group: "
        f"source={group.source} "
        f"shop_id={group.shop_id} "
        f"shop_source_id={group.shop_source_id} "
        f"shop_name={group.shop_name} "
        f"category_raw={_value(group.category_raw)} "
        f"count={group.count}"
    )


def _value(value: object | None) -> object:
    if value is None or value == "":
        return "-"
    return value


def _coverage_pct(categorized_products: int, total_products: int) -> Decimal:
    if total_products == 0:
        return Decimal("0.00")
    return (Decimal(categorized_products) * Decimal("100") / Decimal(total_products)).quantize(
        Decimal("0.01")
    )


def _category_confidence(raw: dict[str, Any] | None) -> Decimal | None:
    if not isinstance(raw, dict):
        return None
    prediction = raw.get("category_prediction")
    if not isinstance(prediction, dict):
        return None
    value = prediction.get("confidence")
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


if __name__ == "__main__":
    raise SystemExit(main())
