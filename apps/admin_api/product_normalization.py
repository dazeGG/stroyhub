from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session
from stroyhub.catalog.normalization_queue import (
    NormalizationQueueFilters,
    NormalizationQueueState,
    ProductNormalizationQueue,
)
from stroyhub.catalog.product_bulk_normalization import (
    ProductBulkNormalizationFilters,
    ProductBulkNormalizationService,
)
from stroyhub.db import get_session

from apps.admin_api.validation import ActorName, ReasonText

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


class BulkNormalizationRequest(BaseModel):
    source: str | None = None
    shop_id: int | None = Field(default=None, gt=0)
    category_id: int | None = Field(default=None, gt=0)
    q: str | None = None
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0)
    dry_run: bool = True
    actor: ActorName | None = "admin"
    reason: ReasonText | None = None


class BulkNormalizationItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source_product_id: int
    title: str
    normalized_title: str
    canonical_product_id: int | None
    match_id: int | None


class BulkNormalizationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    dry_run: bool
    total: int
    page_size: int
    would_create: int
    created: int
    skipped_became_candidate: int
    skipped_already_accepted: int
    skipped_ineligible: int
    skipped_needs_review: int
    followup_candidates_created: int
    items: tuple[BulkNormalizationItemResponse, ...]


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


@router.post("/bulk-create-canonicals", response_model=BulkNormalizationResponse)
def bulk_create_canonicals(
    payload: BulkNormalizationRequest,
    session: Annotated[Session, Depends(get_session)],
) -> BulkNormalizationResponse:
    result = ProductBulkNormalizationService(session).run(
        ProductBulkNormalizationFilters(
            source=payload.source,
            shop_id=payload.shop_id,
            category_id=payload.category_id,
            q=payload.q,
            limit=payload.limit,
            offset=payload.offset,
            dry_run=payload.dry_run,
            actor=payload.actor,
            reason=payload.reason,
        )
    )
    if not payload.dry_run:
        session.commit()
    return BulkNormalizationResponse.model_validate(result)
