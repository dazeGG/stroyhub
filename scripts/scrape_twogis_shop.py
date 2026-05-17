#!/usr/bin/env python
import argparse
from collections.abc import Sequence

from stroyhub.db import SessionLocal
from stroyhub.scraping import persist_twogis_scrape_result, scrape_twogis_branch

DEFAULT_BRANCH_ID = "70000001007229923"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scrape one 2GIS branch without Celery.")
    parser.add_argument("branch_id", nargs="?", default=DEFAULT_BRANCH_ID)
    parser.add_argument("--page-size", type=int, default=50)
    parser.add_argument("--max-pages", type=int, default=100)
    parser.add_argument("--locale", default="ru_RU")
    parser.add_argument("--persist", action="store_true")
    parser.add_argument("--shop-name")
    args = parser.parse_args(argv)

    result = scrape_twogis_branch(
        branch_id=args.branch_id,
        page_size=args.page_size,
        max_pages=args.max_pages,
        locale=args.locale,
    )
    priced_products = sum(1 for product in result.products if product.price is not None)

    print(
        "scrape summary: "
        f"branch_id={result.branch_id} "
        f"total={result.total} "
        f"pages={result.pages_seen} "
        f"items={result.items_seen} "
        f"parsed={len(result.products)} "
        f"priced={priced_products} "
        f"pinned={result.pinned_items_seen} "
        f"completeness={result.completeness} "
        f"stop_reason={result.stop_reason}"
    )

    if args.persist:
        with SessionLocal() as session:
            persist_result = persist_twogis_scrape_result(
                session,
                result,
                shop_name=args.shop_name,
            )
            session.commit()

        print(
            "persist summary: "
            f"shop_id={persist_result.shop_id} "
            f"scrape_run_id={persist_result.scrape_run_id} "
            f"source_products_saved={persist_result.source_products_saved} "
            f"price_snapshots_saved={persist_result.price_snapshots_saved} "
            f"scrape_status={persist_result.scrape_status}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
