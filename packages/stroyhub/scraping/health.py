from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stroyhub.models.tables import ScrapeRun


@dataclass(frozen=True, kw_only=True)
class ScrapeHealthFilters:
    source: str | None = None
    shop_id: int | None = None
    status: str | None = None
    limit: int = 20


@dataclass(frozen=True, kw_only=True)
class ScrapeStatusCount:
    status: str
    count: int


@dataclass(frozen=True, kw_only=True)
class RecentScrapeRun:
    id: int
    source: str
    shop_id: int | None
    status: str
    started_at: datetime
    finished_at: datetime | None
    items_seen: int
    items_saved: int
    error: str | None


@dataclass(frozen=True, kw_only=True)
class ScrapeHealth:
    status_counts: list[ScrapeStatusCount]
    recent_runs: list[RecentScrapeRun]


class ScrapeHealthCatalog:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_health(self, filters: ScrapeHealthFilters) -> ScrapeHealth:
        base_filters = self._where_filters(filters)

        counts_statement = (
            select(ScrapeRun.status, func.count(ScrapeRun.id))
            .where(*base_filters)
            .group_by(ScrapeRun.status)
            .order_by(ScrapeRun.status.asc())
        )
        runs_statement = (
            select(ScrapeRun)
            .where(*base_filters)
            .order_by(ScrapeRun.started_at.desc(), ScrapeRun.id.desc())
            .limit(filters.limit)
        )

        return ScrapeHealth(
            status_counts=[
                ScrapeStatusCount(status=status, count=count)
                for status, count in self._session.execute(counts_statement)
            ],
            recent_runs=[
                RecentScrapeRun(
                    id=run.id,
                    source=run.source,
                    shop_id=run.shop_id,
                    status=run.status,
                    started_at=run.started_at,
                    finished_at=run.finished_at,
                    items_seen=run.items_seen,
                    items_saved=run.items_saved,
                    error=run.error,
                )
                for run in self._session.scalars(runs_statement)
            ],
        )

    def _where_filters(self, filters: ScrapeHealthFilters) -> list[Any]:
        where_filters: list[Any] = []

        if filters.source is not None:
            source = filters.source.strip()
            if source:
                where_filters.append(ScrapeRun.source == source)

        if filters.shop_id is not None:
            where_filters.append(ScrapeRun.shop_id == filters.shop_id)

        if filters.status is not None:
            status = filters.status.strip()
            if status:
                where_filters.append(ScrapeRun.status == status)

        return where_filters
