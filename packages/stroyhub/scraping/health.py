from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from stroyhub.models.tables import ScrapeRun, SourceProduct


@dataclass(frozen=True, kw_only=True)
class ScrapeHealthFilters:
    source: str | None = None
    shop_id: int | None = None
    status: str | None = None
    limit: int = 20
    include_catalog_pipeline: bool = True


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
class CatalogPipelineStatusCount:
    stage: str
    status: str
    count: int


@dataclass(frozen=True, kw_only=True)
class ScrapeHealth:
    status_counts: list[ScrapeStatusCount]
    recent_runs: list[RecentScrapeRun]
    catalog_pipeline_status_counts: list[CatalogPipelineStatusCount]


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
            catalog_pipeline_status_counts=(
                self._catalog_pipeline_status_counts(filters)
                if filters.include_catalog_pipeline
                else []
            ),
        )

    def _catalog_pipeline_status_counts(
        self,
        filters: ScrapeHealthFilters,
    ) -> list[CatalogPipelineStatusCount]:
        base_filters: list[Any] = [SourceProduct.is_active.is_(True)]
        if filters.source is not None:
            source = filters.source.strip()
            if source:
                base_filters.append(SourceProduct.source == source)
        if filters.shop_id is not None:
            base_filters.append(SourceProduct.shop_id == filters.shop_id)

        counts: dict[tuple[str, str], int] = {}
        quality_type = func.jsonb_typeof(SourceProduct.raw["catalog_quality"])
        quality_is_object = quality_type == "object"
        missing_count = self._session.scalar(
            select(func.count(SourceProduct.id)).where(
                *base_filters,
                or_(quality_type.is_(None), quality_type != "object"),
            )
        )
        if missing_count:
            counts[("pipeline", "missing")] = int(missing_count)

        pipeline_status = _json_status(SourceProduct.raw["catalog_quality"]["status"])
        for status, count in self._session.execute(
            select(pipeline_status, func.count(SourceProduct.id))
            .where(*base_filters, quality_is_object)
            .group_by(pipeline_status)
        ):
            counts[("pipeline", status)] = int(count)

        for stage in ("cleanup", "attributes", "categorization", "normalization"):
            stage_value = SourceProduct.raw["catalog_quality"][stage]
            stage_status = _json_status(stage_value["status"])
            for status, count in self._session.execute(
                select(stage_status, func.count(SourceProduct.id))
                .where(
                    *base_filters,
                    quality_is_object,
                    func.jsonb_typeof(stage_value) == "object",
                )
                .group_by(stage_status)
            ):
                counts[(stage, status)] = int(count)

        return [
            CatalogPipelineStatusCount(stage=stage, status=status, count=count)
            for (stage, status), count in sorted(counts.items())
        ]

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


def _json_status(value: Any) -> Any:
    return func.coalesce(func.nullif(value.astext, ""), "unknown")
