#!/usr/bin/env python
# ruff: noqa: E402
import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy import select
from sqlalchemy.orm import Session
from stroyhub.db import SessionLocal
from stroyhub.models import Shop
from stroyhub.scraping.scheduler import list_due_shops

import apps.worker.tasks as worker_tasks

SOURCE_TYPE_CHOICES = ("2gis", "official_api", "official_html")


@dataclass(frozen=True, kw_only=True)
class SourceControlSummary:
    mode: str
    shops_total: int
    shops_scheduled: int
    shops_skipped_unsupported: int
    shops_failed: int
    shops_partial: int


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run or enqueue source-aware shop scraping controls."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    due_parser = subparsers.add_parser(
        "due",
        help="enqueue or run due shop source records",
    )
    due_parser.add_argument("--source", help="Filter by source name, e.g. 2gis or unicom")
    due_parser.add_argument("--source-type", choices=SOURCE_TYPE_CHOICES)
    due_parser.add_argument("--limit", type=int)
    due_parser.add_argument(
        "--sync",
        action="store_true",
        help="Run matching source records in this process instead of enqueueing Celery tasks.",
    )

    shop_parser = subparsers.add_parser(
        "shop",
        help="enqueue or run one shop source record",
    )
    identifier_group = shop_parser.add_mutually_exclusive_group(required=True)
    identifier_group.add_argument("--shop-id", type=int)
    identifier_group.add_argument("--source-id", help="Source-specific shop id")
    shop_parser.add_argument("--source", help="Required with --source-id")
    shop_parser.add_argument(
        "--sync",
        action="store_true",
        help="Run the source record in this process instead of enqueueing a Celery task.",
    )

    args = parser.parse_args(argv)

    with SessionLocal() as session:
        if args.command == "due":
            summary = run_due_sources(
                session,
                source=args.source,
                source_type=args.source_type,
                limit=args.limit,
                sync=args.sync,
            )
            _print_due_summary(summary, source=args.source, source_type=args.source_type)
            return 1 if summary.shops_failed or summary.shops_partial else 0

        if args.source_id and not args.source:
            parser.error("--source is required with --source-id")

        shop = _get_shop(
            session,
            shop_id=args.shop_id,
            source=args.source,
            source_id=args.source_id,
        )
        if shop is None:
            print("source scrape failure: shop not found")
            return 1

        result = dispatch_source_scrape(shop, sync=args.sync)
        _print_shop_result(shop, result, mode="sync" if args.sync else "enqueue")
        return 1 if result.get("status") in {"failed", "partial"} else 0


def run_due_sources(
    session: Session,
    *,
    source: str | None,
    source_type: str | None,
    limit: int | None,
    sync: bool,
) -> SourceControlSummary:
    shops = list_due_shops(
        session,
        now=datetime.now(UTC),
        source=source,
        source_type=source_type,
        limit=limit,
    )
    shops_scheduled = 0
    shops_skipped_unsupported = 0
    shops_failed = 0
    shops_partial = 0

    for shop in shops:
        if shop.source not in worker_tasks.SUPPORTED_SCHEDULED_SOURCES:
            shops_skipped_unsupported += 1
            print(
                "source scrape skipped: "
                f"shop_id={shop.id} "
                f"source={shop.source} "
                f"source_type={shop.source_type} "
                "reason=unsupported_source"
            )
            continue

        result = dispatch_source_scrape(shop, sync=sync)
        shops_scheduled += 1
        if result.get("status") == "failed":
            shops_failed += 1
        if result.get("status") == "partial":
            shops_partial += 1
        _print_shop_result(shop, result, mode="sync" if sync else "enqueue")

    return SourceControlSummary(
        mode="sync" if sync else "enqueue",
        shops_total=len(shops),
        shops_scheduled=shops_scheduled,
        shops_skipped_unsupported=shops_skipped_unsupported,
        shops_failed=shops_failed,
        shops_partial=shops_partial,
    )


def dispatch_source_scrape(shop: Shop, *, sync: bool) -> dict[str, Any]:
    if shop.scrape_status == "disabled":
        return {"status": "skipped", "reason": "source_disabled"}
    if shop.source not in worker_tasks.SUPPORTED_SCHEDULED_SOURCES:
        return {"status": "failed", "error": "unsupported_source"}

    if sync:
        result = worker_tasks.scrape_shop.run(shop.id)
        if not isinstance(result, dict):
            return {"status": "failed", "error": "unexpected_task_result"}
        return result

    worker_tasks.scrape_shop.delay(shop.id)
    return {"status": "queued"}


def _get_shop(
    session: Session,
    *,
    shop_id: int | None,
    source: str | None,
    source_id: str | None,
) -> Shop | None:
    if shop_id is not None:
        return session.get(Shop, shop_id)

    statement = select(Shop).where(Shop.source == source, Shop.source_id == source_id)
    return session.scalar(statement)


def _print_shop_result(shop: Shop, result: dict[str, Any], *, mode: str) -> None:
    print(
        "source scrape result: "
        f"mode={mode} "
        f"shop_id={shop.id} "
        f"source={shop.source} "
        f"source_type={shop.source_type} "
        f"source_id={shop.source_id} "
        f"name={shop.name} "
        f"status={result.get('status', '-')} "
        f"products_seen={result.get('products_seen', '-')} "
        f"products_saved={result.get('products_saved', '-')} "
        f"price_snapshots_saved={result.get('price_snapshots_saved', '-')} "
        f"reason={result.get('reason', result.get('error', '-'))}"
    )


def _print_due_summary(
    summary: SourceControlSummary,
    *,
    source: str | None,
    source_type: str | None,
) -> None:
    print(
        "due source scrape summary: "
        f"mode={summary.mode} "
        f"source={source or '-'} "
        f"source_type={source_type or '-'} "
        f"shops_total={summary.shops_total} "
        f"shops_scheduled={summary.shops_scheduled} "
        f"shops_skipped_unsupported={summary.shops_skipped_unsupported} "
        f"shops_partial={summary.shops_partial} "
        f"shops_failed={summary.shops_failed}"
    )


if __name__ == "__main__":
    raise SystemExit(main())
