#!/usr/bin/env python
import argparse
from collections.abc import Sequence

from stroyhub.catalog.shop_candidates import discover_twogis_candidates
from stroyhub.scraping import scrape_twogis_branch


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate candidate 2GIS Yakutsk construction-material shops."
    )
    parser.add_argument("--page-size", type=int, default=50)
    parser.add_argument("--max-pages", type=int, default=20)
    parser.add_argument("--discovery-pages", type=int, default=5)
    parser.add_argument("--locale", default="ru_RU")
    args = parser.parse_args(argv)

    print(
        "\t".join(
            [
                "branch_id",
                "name",
                "address",
                "rubrics",
                "classification",
                "total",
                "pages_seen",
                "items_seen",
                "products_parsed",
                "priced_products",
                "completeness",
                "stop_reason",
            ]
        )
    )

    for candidate in discover_twogis_candidates(max_pages=args.discovery_pages):
        try:
            result = scrape_twogis_branch(
                branch_id=candidate.source_id,
                page_size=args.page_size,
                max_pages=args.max_pages,
                locale=args.locale,
            )
        except Exception as exc:
            print(
                "\t".join(
                    [
                        candidate.source_id,
                        candidate.display_name,
                        candidate.address,
                        candidate.rubrics,
                        "failed",
                        "",
                        "",
                        "",
                        "",
                        "",
                        type(exc).__name__,
                        str(exc),
                    ]
                )
            )
            continue

        priced_products = sum(1 for product in result.products if product.price is not None)
        classification = "active" if priced_products > 0 else "no_prices"
        print(
            "\t".join(
                    [
                        candidate.source_id,
                        candidate.display_name,
                        candidate.address,
                        candidate.rubrics,
                    classification,
                    str(result.total),
                    str(result.pages_seen),
                    str(result.items_seen),
                    str(len(result.products)),
                    str(priced_products),
                    result.completeness,
                    result.stop_reason,
                ]
            )
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
