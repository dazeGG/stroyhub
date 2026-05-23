#!/usr/bin/env python
import argparse
import importlib
import sys
from collections.abc import Sequence
from pathlib import Path

DEFAULT_SETUP_SCRAPE_INTERVAL = 7 * 24 * 60 * 60

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

seed_categories = importlib.import_module("seed_categories").main
seed_metalltorg_source = importlib.import_module("seed_metalltorg_source").main
seed_unicom_source = importlib.import_module("seed_unicom_source").main


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the repeatable local data collection setup: normalized categories first, "
            "then official shop sources and the initial 2GIS scrape whitelist."
        )
    )
    parser.add_argument("--scrape-interval", type=int, default=DEFAULT_SETUP_SCRAPE_INTERVAL)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    category_args = ["--dry-run"] if args.dry_run else []
    metalltorg_args = ["--scrape-interval", str(args.scrape_interval)]
    unicom_args = ["--scrape-interval", str(args.scrape_interval)]
    if args.dry_run:
        metalltorg_args.append("--dry-run")
        unicom_args.append("--dry-run")
    else:
        unicom_args.append("--discover-categories")

    print("== Seed normalized categories ==")
    category_result = seed_categories(category_args)
    if category_result != 0:
        return category_result

    print("== Seed official Unicom source ==")
    unicom_result = seed_unicom_source(unicom_args)
    if unicom_result != 0:
        return unicom_result

    print("== Seed official Metalltorg source ==")
    metalltorg_result = seed_metalltorg_source(metalltorg_args)
    if metalltorg_result != 0:
        return metalltorg_result

    print("== 2GIS candidates are approved through admin candidate review ==")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
