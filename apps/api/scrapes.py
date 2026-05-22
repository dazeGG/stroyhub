from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session
from stroyhub.db import get_session
from stroyhub.models import Shop
from stroyhub.scraping.health import ScrapeHealthCatalog, ScrapeHealthFilters
from stroyhub.scraping.runner import run_shop_scrape

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


class ScrapeHealthResponse(BaseModel):
    status_counts: list[ScrapeStatusCountResponse]
    recent_runs: list[RecentScrapeRunResponse]


class ShopScrapeRunResponse(BaseModel):
    shop_id: int
    source: str | None = None
    source_type: str | None = None
    status: str
    duration_seconds: float | None = None
    products_seen: int | None = None
    products_saved: int | None = None
    price_snapshots_saved: int | None = None
    reason: str | None = None
    error: str | None = None


@router.get("/health", response_model=ScrapeHealthResponse)
def get_scrape_health(
    session: Annotated[Session, Depends(get_session)],
    source: str | None = None,
    shop: int | None = None,
    status: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ScrapeHealthResponse:
    filters = ScrapeHealthFilters(
        source=source,
        shop_id=shop,
        status=status,
        limit=limit,
    )
    health = ScrapeHealthCatalog(session).get_health(filters)
    return ScrapeHealthResponse(
        status_counts=[
            ScrapeStatusCountResponse.model_validate(item) for item in health.status_counts
        ],
        recent_runs=[
            RecentScrapeRunResponse.model_validate(item) for item in health.recent_runs
        ],
    )


@router.post("/shops/{shop_id}/run", response_model=ShopScrapeRunResponse)
def run_shop_scrape_now(
    shop_id: int,
    session: Annotated[Session, Depends(get_session)],
) -> ShopScrapeRunResponse:
    if session.get(Shop, shop_id) is None:
        raise HTTPException(status_code=404, detail="shop not found")

    result = run_shop_scrape(session, shop_id)
    return ShopScrapeRunResponse(**result)
