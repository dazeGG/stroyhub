#!/usr/bin/env python
import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from stroyhub.db import SessionLocal
from stroyhub.models import Shop
from stroyhub.scraping import persist_twogis_scrape_result, scrape_twogis_branch
from stroyhub.scraping.scheduler import mark_shop_scrape_completion, mark_shop_scrape_failure

TWOGIS_SOURCE = "2gis"


@dataclass(frozen=True, kw_only=True)
class WhitelistScrapeTotals:
    shops_total: int
    shops_scraped: int
    shops_partial: int
    shops_failed: int
    source_products_saved: int
    price_snapshots_saved: int


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scrape every active 2GIS shop in the local whitelist and persist results."
    )
    parser.add_argument("--page-size", type=int, default=50)
    parser.add_argument("--max-pages", type=int, default=100)
    parser.add_argument("--locale", default="ru_RU")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args(argv)

    totals = WhitelistScrapeTotals(
        shops_total=0,
        shops_scraped=0,
        shops_partial=0,
        shops_failed=0,
        source_products_saved=0,
        price_snapshots_saved=0,
    )

    with SessionLocal() as session:
        shops = _list_whitelisted_twogis_shops(session, limit=args.limit)
        totals = _replace_totals(totals, shops_total=len(shops))

        for shop in shops:
            try:
                result = scrape_twogis_branch(
                    branch_id=shop.source_id,
                    page_size=args.page_size,
                    max_pages=args.max_pages,
                    locale=args.locale,
                )
                persisted = persist_twogis_scrape_result(
                    session,
                    result,
                    shop_name=shop.name,
                    finished_at=datetime.now(UTC),
                )
                mark_shop_scrape_completion(
                    shop,
                    completed_at=datetime.now(UTC),
                    scrape_status=persisted.scrape_status,
                )
                session.commit()

                totals = _replace_totals(
                    totals,
                    shops_scraped=totals.shops_scraped + 1,
                    shops_partial=(
                        totals.shops_partial + 1
                        if persisted.scrape_status != "success"
                        else totals.shops_partial
                    ),
                    source_products_saved=(
                        totals.source_products_saved + persisted.source_products_saved
                    ),
                    price_snapshots_saved=(
                        totals.price_snapshots_saved + persisted.price_snapshots_saved
                    ),
                )
                _print_shop_summary(shop=shop, result=result, persisted=persisted)
            except Exception as exc:
                session.rollback()
                failed_at = datetime.now(UTC)
                failed_shop = session.get(Shop, shop.id)
                if failed_shop is not None:
                    mark_shop_scrape_failure(failed_shop, failed_at=failed_at, error=str(exc))
                    session.commit()

                totals = _replace_totals(totals, shops_failed=totals.shops_failed + 1)
                print(
                    "shop scrape failure: "
                    f"shop_id={shop.id} "
                    f"branch_id={shop.source_id} "
                    f"name={shop.name} "
                    f"error={exc}"
                )

    _print_totals(totals)
    return 1 if totals.shops_failed or totals.shops_partial else 0


def _list_whitelisted_twogis_shops(session, *, limit: int | None) -> list[Shop]:  # type: ignore[no-untyped-def]
    statement = (
        select(Shop)
        .where(Shop.source == TWOGIS_SOURCE, Shop.scrape_status != "disabled")
        .order_by(Shop.id.asc())
    )
    if limit is not None:
        statement = statement.limit(limit)

    return list(session.scalars(statement))


def _replace_totals(totals: WhitelistScrapeTotals, **changes: int) -> WhitelistScrapeTotals:
    values = {
        "shops_total": totals.shops_total,
        "shops_scraped": totals.shops_scraped,
        "shops_partial": totals.shops_partial,
        "shops_failed": totals.shops_failed,
        "source_products_saved": totals.source_products_saved,
        "price_snapshots_saved": totals.price_snapshots_saved,
    }
    values.update(changes)
    return WhitelistScrapeTotals(**values)


def _print_shop_summary(*, shop: Shop, result, persisted) -> None:  # type: ignore[no-untyped-def]
    print(
        "shop scrape summary: "
        f"shop_id={shop.id} "
        f"branch_id={shop.source_id} "
        f"name={shop.name} "
        f"total={result.total} "
        f"pages={result.pages_seen} "
        f"items={result.items_seen} "
        f"parsed={len(result.products)} "
        f"completeness={result.completeness} "
        f"stop_reason={result.stop_reason} "
        f"source_products_saved={persisted.source_products_saved} "
        f"price_snapshots_saved={persisted.price_snapshots_saved} "
        f"scrape_status={persisted.scrape_status}"
    )


def _print_totals(totals: WhitelistScrapeTotals) -> None:
    print(
        "whitelist scrape summary: "
        f"shops_total={totals.shops_total} "
        f"shops_scraped={totals.shops_scraped} "
        f"shops_partial={totals.shops_partial} "
        f"shops_failed={totals.shops_failed} "
        f"source_products_saved={totals.source_products_saved} "
        f"price_snapshots_saved={totals.price_snapshots_saved}"
    )


if __name__ == "__main__":
    raise SystemExit(main())
