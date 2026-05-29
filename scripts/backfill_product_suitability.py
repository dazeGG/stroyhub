from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import cast

from sqlalchemy import and_, select
from stroyhub.catalog.eligibility import with_catalog_eligibility
from stroyhub.catalog.eligibility_readiness import count_missing_catalog_eligibility
from stroyhub.catalog.product_suitability import ProductSuitabilityEvaluator
from stroyhub.catalog.query_helpers import latest_price_subquery
from stroyhub.db import SessionLocal
from stroyhub.ml.not_product_classifier import (
    NotProductClassifierModelUnavailableError,
    PatronClassifier,
)
from stroyhub.models import Category, Shop, SourceProduct
from stroyhub.parsers.common import ParsedProduct, PriceKind


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Backfill catalog suitability for existing source products."
    )
    parser.add_argument("--apply", action="store_true", help="Persist changes to the database.")
    parser.add_argument(
        "--include-inactive",
        action="store_true",
        help="Process inactive source products too.",
    )
    parser.add_argument(
        "--allow-rules-fallback",
        action="store_true",
        help="Allow a rules-only run when Patron model artifacts are unavailable.",
    )
    parser.add_argument("--limit", type=int, help="Only process the first N products.")
    parser.add_argument(
        "--require-complete",
        action="store_true",
        help=(
            "Return a non-zero code when active source products still miss "
            "raw.catalog_eligibility after the run."
        ),
    )
    args = parser.parse_args(argv)

    try:
        evaluator = ProductSuitabilityEvaluator.default(
            require_patron=not args.allow_rules_fallback
        )
    except NotProductClassifierModelUnavailableError:
        print("action=blocked")
        print("model_loaded=false")
        print(f"patron_model_dir={PatronClassifier.default_model_dir()}")
        print("error=Patron model is unavailable")
        return 1
    model_loaded = evaluator.patron is not None

    counters: Counter[str] = Counter()
    started_at = datetime.now(UTC)
    remaining_missing = 0

    with SessionLocal() as session:
        latest_prices = latest_price_subquery()
        statement = (
            select(
                SourceProduct,
                Shop,
                Category,
                latest_prices.c.latest_price,
                latest_prices.c.latest_price_kind,
                latest_prices.c.latest_currency,
                latest_prices.c.latest_unit_raw,
                latest_prices.c.latest_source_updated_at,
                latest_prices.c.latest_parsed_at,
            )
            .join(Shop, Shop.id == SourceProduct.shop_id)
            .outerjoin(Category, Category.id == SourceProduct.category_id)
            .outerjoin(
                latest_prices,
                and_(
                    latest_prices.c.source_product_id == SourceProduct.id,
                    latest_prices.c.row_number == 1,
                ),
            )
            .order_by(SourceProduct.id)
        )
        if not args.include_inactive:
            statement = statement.where(SourceProduct.is_active.is_(True))
        if args.limit is not None:
            statement = statement.limit(args.limit)

        rows = list(session.execute(statement))
        for (
            source_product,
            shop,
            category,
            latest_price,
            latest_price_kind,
            latest_currency,
            latest_unit_raw,
            latest_source_updated_at,
            latest_parsed_at,
        ) in rows:
            product = _parsed_product(
                source_product,
                shop_source_id=shop.source_id,
                latest_price=_LatestPrice(
                    price=latest_price,
                    currency=latest_currency or "RUB",
                    unit_raw=latest_unit_raw,
                    price_kind=_price_kind(latest_price_kind),
                    source_updated_at=latest_source_updated_at,
                    parsed_at=latest_parsed_at,
                ),
            )
            previous_is_not_product = source_product.is_not_product
            previous_status = _catalog_status(source_product.raw)
            suitability = evaluator.evaluate(
                product,
                existing_product=source_product,
                shop_name=shop.name,
                shop_url=shop.url,
                category_name=category.name if category is not None else None,
                category_path=_category_path(category),
            )

            source_product.raw = with_catalog_eligibility(
                product.raw,
                suitability,
                existing_raw=source_product.raw,
            )
            source_product.is_not_product = suitability.is_not_product

            counters["processed"] += 1
            counters[f"source:{source_product.source}"] += 1
            counters[f"method:{suitability.method}"] += 1
            counters[f"status:{suitability.status}"] += 1
            if previous_is_not_product != source_product.is_not_product:
                counters["is_not_product_changed"] += 1
            if previous_status != suitability.status:
                counters["status_changed"] += 1

        if args.apply:
            session.commit()
            action = "applied"
        else:
            session.rollback()
            action = "dry_run"

        remaining_missing = count_missing_catalog_eligibility(
            session,
            include_inactive=args.include_inactive,
        )

    print(f"action={action}")
    print(f"model_loaded={str(model_loaded).lower()}")
    print(f"patron_model_dir={PatronClassifier.default_model_dir()}")
    print(f"started_at={started_at.isoformat()}")
    print(f"missing_catalog_eligibility={remaining_missing}")
    for key in sorted(counters):
        print(f"{key}={counters[key]}")
    if args.require_complete and remaining_missing:
        print("error=missing_catalog_eligibility_remaining")
        return 2
    return 0


def _parsed_product(
    product: SourceProduct,
    *,
    shop_source_id: str,
    latest_price: _LatestPrice,
) -> ParsedProduct:
    raw = dict(product.raw or {})
    return ParsedProduct(
        source=product.source,
        shop_source_id=shop_source_id,
        source_product_id=product.source_product_id,
        title=product.title,
        normalized_title=product.normalized_title,
        fingerprint=product.fingerprint,
        description=product.description,
        category_raw=product.category_raw,
        unit_raw=latest_price.unit_raw or product.unit_raw,
        price=latest_price.price,
        currency=latest_price.currency,
        image_url=product.image_url,
        source_updated_at=latest_price.source_updated_at or product.source_updated_at,
        raw=raw,
        parsed_at=latest_price.parsed_at or product.last_seen_at,
        price_kind=latest_price.price_kind,
    )


def _catalog_status(raw: dict[str, object] | None) -> str | None:
    if raw is None:
        return None
    eligibility = raw.get("catalog_eligibility")
    if not isinstance(eligibility, dict):
        return None
    status = eligibility.get("status")
    return status if isinstance(status, str) else None


def _price_kind(value: object) -> PriceKind:
    if value in {"exact", "from", "range", "unknown"}:
        return cast(PriceKind, value)
    return "unknown"


def _category_path(category: Category | None) -> tuple[str, ...]:
    path: list[str] = []
    current = category
    while current is not None:
        path.append(current.name)
        current = current.parent
    return tuple(reversed(path))


@dataclass(frozen=True, kw_only=True)
class _LatestPrice:
    price: Decimal | None
    currency: str
    unit_raw: str | None
    price_kind: PriceKind
    source_updated_at: datetime | None
    parsed_at: datetime | None


if __name__ == "__main__":
    raise SystemExit(main())
