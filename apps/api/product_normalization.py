from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session
from stroyhub.catalog.normalization_queue import (
    NormalizationQueueFilters,
    NormalizationQueueState,
    ProductNormalizationQueue,
)
from stroyhub.db import get_session

router = APIRouter(prefix="/product-normalization", tags=["product-normalization"])


class NormalizationShopResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    source_id: str
    name: str


class NormalizationLatestPriceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    price: Decimal | None
    currency: str
    unit_raw: str | None
    source_updated_at: datetime | None
    parsed_at: datetime


class CatalogEligibilityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: str
    confidence: str | None
    score: int | None
    reasons: tuple[str, ...]


class NormalizationMatchSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    accepted_match_id: int | None
    accepted_canonical_product_id: int | None
    accepted_canonical_title: str | None
    candidate_count: int
    rejected_count: int


class NormalizationCandidateMatchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    canonical_product_id: int
    canonical_title: str
    canonical_normalized_title: str
    canonical_category_id: int | None
    confidence: Decimal
    method: str
    reason: dict[str, object] | None


class NormalizationQueueItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    state: NormalizationQueueState
    source: str
    source_product_id: str | None
    title: str
    normalized_title: str
    category_id: int | None
    category_slug: str | None
    category_name: str | None
    category_raw: str | None
    unit_raw: str | None
    image_url: str | None
    last_seen_at: datetime
    is_not_product: bool
    shop: NormalizationShopResponse
    latest_price: NormalizationLatestPriceResponse | None
    catalog_eligibility: CatalogEligibilityResponse | None
    match_summary: NormalizationMatchSummaryResponse
    candidate_matches: tuple[NormalizationCandidateMatchResponse, ...]


class NormalizationQueueResponse(BaseModel):
    items: list[NormalizationQueueItemResponse]
    limit: int
    offset: int
    total: int


@router.get("/queue", response_model=NormalizationQueueResponse)
def list_normalization_queue(
    session: Annotated[Session, Depends(get_session)],
    state: NormalizationQueueState | None = None,
    source: str | None = None,
    shop: int | None = None,
    category_id: int | None = None,
    q: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> NormalizationQueueResponse:
    page = ProductNormalizationQueue(session).list_items(
        NormalizationQueueFilters(
            state=state,
            source=source,
            shop_id=shop,
            category_id=category_id,
            q=q,
            limit=limit,
            offset=offset,
        )
    )
    return NormalizationQueueResponse(
        items=[
            NormalizationQueueItemResponse.model_validate(item)
            for item in page.items
        ],
        limit=page.limit,
        offset=page.offset,
        total=page.total,
    )
