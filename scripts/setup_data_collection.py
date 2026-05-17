#!/usr/bin/env python
import argparse
from collections.abc import Sequence

from scripts.seed_categories import main as seed_categories
from scripts.seed_twogis_whitelist import main as seed_twogis_whitelist


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the repeatable local data collection setup: normalized categories first, "
            "then the initial 2GIS scrape whitelist."
        )
    )
    parser.add_argument("--scrape-interval", type=int, default=86400)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    category_args = ["--dry-run"] if args.dry_run else []
    whitelist_args = ["--scrape-interval", str(args.scrape_interval)]
    if args.dry_run:
        whitelist_args.append("--dry-run")

    print("== Seed normalized categories ==")
    category_result = seed_categories(category_args)
    if category_result != 0:
        return category_result

    print("== Seed initial 2GIS whitelist ==")
    return seed_twogis_whitelist(whitelist_args)


if __name__ == "__main__":
    raise SystemExit(main())
