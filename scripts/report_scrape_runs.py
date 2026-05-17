#!/usr/bin/env python
import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session
from stroyhub.db import SessionLocal
from stroyhub.models import ScrapeRun, Shop


@dataclass(frozen=True, kw_only=True)
class ScrapeRunSummary:
    id: int
    source: str
    shop_id: int | None
    shop_name: str | None
    shop_source_id: str | None
    status: str
    started_at: datetime
    finished_at: datetime | None
    items_seen: int
    items_saved: int
    error: str | None
    completeness: str | None
    stop_reason: str | None
    branch_id: str | None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print recent scrape run summaries.")
    parser.add_argument("--source")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args(argv)

    with SessionLocal() as session:
        runs = _list_scrape_runs(
            session,
            source=args.source,
            days=args.days,
            limit=args.limit,
            now=datetime.now(UTC),
        )

    if not runs:
        print("scrape run summary: no runs found")
        return 0

    for run in runs:
        print(_format_run(run))

    return 0


def _list_scrape_runs(
    session: Session,
    *,
    source: str | None,
    days: int | None,
    limit: int | None,
    now: datetime,
) -> list[ScrapeRunSummary]:
    statement = select(ScrapeRun, Shop).outerjoin(Shop, ScrapeRun.shop_id == Shop.id)

    if source is not None:
        statement = statement.where(ScrapeRun.source == source)
    if days is not None and days > 0:
        statement = statement.where(ScrapeRun.started_at >= now - timedelta(days=days))

    statement = statement.order_by(ScrapeRun.started_at.desc(), ScrapeRun.id.desc())
    if limit is not None and limit > 0:
        statement = statement.limit(limit)

    return [_summary_from_row(scrape_run, shop) for scrape_run, shop in session.execute(statement)]


def _summary_from_row(scrape_run: ScrapeRun, shop: Shop | None) -> ScrapeRunSummary:
    raw = scrape_run.raw or {}
    return ScrapeRunSummary(
        id=scrape_run.id,
        source=scrape_run.source,
        shop_id=scrape_run.shop_id,
        shop_name=shop.name if shop is not None else None,
        shop_source_id=shop.source_id if shop is not None else None,
        status=scrape_run.status,
        started_at=scrape_run.started_at,
        finished_at=scrape_run.finished_at,
        items_seen=scrape_run.items_seen,
        items_saved=scrape_run.items_saved,
        error=scrape_run.error,
        completeness=_string_or_none(raw.get("completeness")),
        stop_reason=_string_or_none(raw.get("stop_reason")),
        branch_id=_string_or_none(raw.get("branch_id")),
    )


def _format_run(run: ScrapeRunSummary) -> str:
    return (
        "scrape run: "
        f"id={run.id} "
        f"source={run.source} "
        f"shop_id={_value(run.shop_id)} "
        f"shop_source_id={_value(run.shop_source_id)} "
        f"shop_name={_value(run.shop_name)} "
        f"status={run.status} "
        f"started_at={_format_datetime(run.started_at)} "
        f"finished_at={_value(_format_datetime(run.finished_at))} "
        f"items_seen={run.items_seen} "
        f"items_saved={run.items_saved} "
        f"error={_value(run.error)} "
        f"completeness={_value(run.completeness)} "
        f"stop_reason={_value(run.stop_reason)} "
        f"branch_id={_value(run.branch_id)}"
    )


def _format_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _value(value: object | None) -> object:
    if value is None or value == "":
        return "-"
    return value


def _string_or_none(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


if __name__ == "__main__":
    raise SystemExit(main())
