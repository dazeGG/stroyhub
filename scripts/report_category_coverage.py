#!/usr/bin/env python
import argparse
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

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
class UncategorizedGroup:
    source: str
    shop_id: int
    shop_name: str
    shop_source_id: str
    category_raw: str | None
    count: int
    titles: tuple[str, ...]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Print uncategorized source product groups for taxonomy/rule updates."
    )
    parser.add_argument("--source")
    parser.add_argument("--shop-id", type=int)
    parser.add_argument("--limit-groups", type=int, default=50)
    parser.add_argument("--titles-per-group", type=int, default=3)
    args = parser.parse_args(argv)

    with SessionLocal() as session:
        products = _list_uncategorized_products(
            session,
            source=args.source,
            shop_id=args.shop_id,
        )

    groups = group_uncategorized_products(products, titles_per_group=args.titles_per_group)
    total_products = sum(group.count for group in groups)
    total_groups = len(groups)
    if args.limit_groups > 0:
        groups = groups[: args.limit_groups]

    _print_report(
        groups,
        total_products=total_products,
        total_groups=total_groups,
    )
    return 0


def _list_uncategorized_products(
    session: Session,
    *,
    source: str | None,
    shop_id: int | None,
) -> list[UncategorizedProduct]:
    statement = (
        select(SourceProduct, Shop)
        .join(Shop, SourceProduct.shop_id == Shop.id)
        .where(SourceProduct.category_id.is_(None), SourceProduct.is_active.is_(True))
        .order_by(Shop.name.asc(), SourceProduct.category_raw.asc(), SourceProduct.title.asc())
    )
    if source is not None:
        statement = statement.where(SourceProduct.source == source)
    if shop_id is not None:
        statement = statement.where(SourceProduct.shop_id == shop_id)

    return [
        UncategorizedProduct(
            source=product.source,
            shop_id=shop.id,
            shop_name=shop.name,
            shop_source_id=shop.source_id,
            category_raw=product.category_raw,
            title=product.title,
        )
        for product, shop in session.execute(statement)
    ]


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
) -> None:
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


if __name__ == "__main__":
    raise SystemExit(main())
