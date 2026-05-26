#!/usr/bin/env python

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import exists, not_, select
from sqlalchemy.orm import Session
from stroyhub.catalog.categorization import CategoryPrediction, RuleBasedCategorizer
from stroyhub.catalog.source_category_mappings import categorizer_for_session
from stroyhub.db import SessionLocal
from stroyhub.db.repositories import CategoryRepository, CategoryUpsert
from stroyhub.models import CategoryOverride, SourceProduct


@dataclass(frozen=True, kw_only=True)
class CategoryBackfillResult:
    products_seen: int
    changed: int
    unchanged: int
    unmatched: int
    dry_run: bool


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Backfill source_products.category_id using current category rules."
    )
    parser.add_argument("--source")
    parser.add_argument("--shop-id", type=int)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    with SessionLocal() as session:
        products = _list_source_products(session, source=args.source, shop_id=args.shop_id)
        result = backfill_products(
            products,
            category_repository=CategoryRepository(session),
            categorizer=categorizer_for_session(session),
            dry_run=args.dry_run,
        )
        if args.dry_run:
            session.rollback()
        else:
            session.commit()

    print(
        "category backfill summary: "
        f"products_seen={result.products_seen} "
        f"changed={result.changed} "
        f"unchanged={result.unchanged} "
        f"unmatched={result.unmatched} "
        f"dry_run={result.dry_run}"
    )
    return 0


def _list_source_products(
    session: Session,
    *,
    source: str | None,
    shop_id: int | None,
) -> list[SourceProduct]:
    statement = (
        select(SourceProduct)
        .where(SourceProduct.is_active.is_(True))
        .where(
            not_(
                exists(
                    select(CategoryOverride.id).where(
                        CategoryOverride.source_product_id == SourceProduct.id,
                        CategoryOverride.status == "active",
                    )
                )
            )
        )
        .order_by(SourceProduct.id.asc())
    )
    if source is not None:
        statement = statement.where(SourceProduct.source == source)
    if shop_id is not None:
        statement = statement.where(SourceProduct.shop_id == shop_id)
    return list(session.scalars(statement))


def backfill_products(
    products: Sequence[Any],
    *,
    category_repository: Any,
    categorizer: RuleBasedCategorizer,
    dry_run: bool,
) -> CategoryBackfillResult:
    changed = 0
    unchanged = 0
    unmatched = 0

    for product in products:
        if _has_active_category_override(product):
            unchanged += 1
            continue
        category_id = _category_id_for_product(
            category_repository=category_repository,
            categorizer=categorizer,
            product=product,
        )
        if category_id is None:
            unmatched += 1
            continue
        if product.category_id == category_id:
            unchanged += 1
            continue

        changed += 1
        if not dry_run:
            product.category_id = category_id

    return CategoryBackfillResult(
        products_seen=len(products),
        changed=changed,
        unchanged=unchanged,
        unmatched=unmatched,
        dry_run=dry_run,
    )


def _has_active_category_override(product: Any) -> bool:
    product_values = getattr(product, "__dict__", None)
    if isinstance(product_values, dict):
        if "category_overrides" not in product_values:
            return False
        overrides = product_values["category_overrides"]
    else:
        overrides = getattr(product, "category_overrides", None)
    if not isinstance(overrides, (list, tuple)):
        return False
    return any(getattr(override, "status", None) == "active" for override in overrides)


def _category_id_for_product(
    *,
    category_repository: Any,
    categorizer: RuleBasedCategorizer,
    product: Any,
) -> int | None:
    prediction = categorizer.categorize(
        title=product.title,
        source=product.source,
        category_raw=product.category_raw,
        description=product.description,
    )
    if prediction is None:
        return None
    return _upsert_prediction_category(category_repository, prediction)


def _upsert_prediction_category(
    category_repository: Any,
    prediction: CategoryPrediction,
) -> int:
    parent_id = None
    if prediction.parent_slug is not None and prediction.parent_name is not None:
        parent = category_repository.upsert(
            CategoryUpsert(slug=prediction.parent_slug, name=prediction.parent_name)
        )
        parent_id = parent.id

    category = category_repository.upsert(
        CategoryUpsert(
            slug=prediction.category_slug,
            name=prediction.category_name,
            parent_id=parent_id,
        )
    )
    return category.id


if __name__ == "__main__":
    raise SystemExit(main())
