from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session
from stroyhub.db import get_session
from stroyhub.scraping.health import ScrapeHealthCatalog, ScrapeHealthFilters

from apps.admin_api.validation import ScrapeRunStatus

router = APIRouter(prefix="/scrapes", tags=["scrapes"])


class ScrapeStatusCountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: str
    count: int


class RecentScrapeRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    shop_id: int | None
    status: str
    started_at: datetime
    finished_at: datetime | None
    items_seen: int
    items_saved: int
    error: str | None


class CatalogPipelineStatusCountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    stage: str
    status: str
    count: int


class ScrapeHealthResponse(BaseModel):
    status_counts: list[ScrapeStatusCountResponse]
    recent_runs: list[RecentScrapeRunResponse]
    catalog_pipeline_status_counts: list[CatalogPipelineStatusCountResponse]


@router.get("/health", response_model=ScrapeHealthResponse)
def get_scrape_health(
    session: Annotated[Session, Depends(get_session)],
    source: str | None = None,
    shop: Annotated[int | None, Query(gt=0)] = None,
    status: ScrapeRunStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    include_catalog_pipeline: bool = True,
) -> ScrapeHealthResponse:
    filters = ScrapeHealthFilters(
        source=source,
        shop_id=shop,
        status=status,
        limit=limit,
        include_catalog_pipeline=include_catalog_pipeline,
    )
    health = ScrapeHealthCatalog(session).get_health(filters)
    return ScrapeHealthResponse(
        status_counts=[
            ScrapeStatusCountResponse.model_validate(item) for item in health.status_counts
        ],
        recent_runs=[
            RecentScrapeRunResponse.model_validate(item) for item in health.recent_runs
        ],
        catalog_pipeline_status_counts=[
            CatalogPipelineStatusCountResponse.model_validate(item)
            for item in health.catalog_pipeline_status_counts
        ],
    )
