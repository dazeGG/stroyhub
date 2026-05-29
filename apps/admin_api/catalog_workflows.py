from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session
from stroyhub.catalog.workflow_queues import (
    CatalogWorkflowAutoAcceptService,
    CatalogWorkflowBatchItemStatus,
    CatalogWorkflowQueueCatalog,
    CatalogWorkflowQueueFilters,
    CatalogWorkflowQueueName,
)
from stroyhub.db import get_session

from apps.admin_api.validation import ActorName, ReasonText

router = APIRouter(prefix="/catalog-workflows", tags=["catalog-workflows"])


class WorkflowDashboardCountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    queue: CatalogWorkflowQueueName
    count: int


class WorkflowDashboardResponse(BaseModel):
    counts: tuple[WorkflowDashboardCountResponse, ...]


class WorkflowShopResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    source_id: str
    name: str


class WorkflowCategoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    name: str


class WorkflowLatestPriceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    price: Decimal | None
    price_kind: str
    price_text: str | None
    currency: str
    unit_raw: str | None
    source_updated_at: datetime | None
    parsed_at: datetime


class WorkflowReasonResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    stage: str
    status: str | None
    action: str | None
    reasons: tuple[str, ...]
    blockers: tuple[str, ...]
    message: str | None = None


class WorkflowCandidateMatchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    canonical_product_id: int
    canonical_title: str
    canonical_normalized_title: str
    canonical_category_id: int | None
    confidence: Decimal
    method: str
    reason: dict[str, Any] | None


class WorkflowMatchSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    accepted_match_id: int | None
    accepted_canonical_product_id: int | None
    accepted_canonical_title: str | None
    candidate_count: int
    rejected_count: int


class WorkflowQueueItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    queue: CatalogWorkflowQueueName
    source: str
    source_product_id: str | None
    title: str
    normalized_title: str
    category_id: int | None
    category: WorkflowCategoryResponse | None
    category_raw: str | None
    unit_raw: str | None
    image_url: str | None
    last_seen_at: datetime
    is_not_product: bool
    shop: WorkflowShopResponse
    latest_price: WorkflowLatestPriceResponse | None
    catalog_quality: dict[str, Any] | None
    reasons: tuple[WorkflowReasonResponse, ...]
    match_summary: WorkflowMatchSummaryResponse
    candidate_matches: tuple[WorkflowCandidateMatchResponse, ...]


class WorkflowQueueResponse(BaseModel):
    queue: CatalogWorkflowQueueName
    items: tuple[WorkflowQueueItemResponse, ...]
    limit: int
    offset: int
    total: int


class WorkflowAutoAcceptRequest(BaseModel):
    source: str | None = None
    shop_id: int | None = Field(default=None, gt=0)
    category_id: int | None = Field(default=None, gt=0)
    q: str | None = None
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0)
    dry_run: bool = True
    actor: ActorName | None = "admin"
    reason: ReasonText | None = None


class WorkflowAutoAcceptItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source_product_id: int
    title: str
    action: str | None
    status: CatalogWorkflowBatchItemStatus
    reason: str
    canonical_product_id: int | None
    match_id: int | None


class WorkflowAutoAcceptResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    dry_run: bool
    total: int
    page_size: int
    would_accept: int
    accepted: int
    skipped: int
    items: tuple[WorkflowAutoAcceptItemResponse, ...]


@router.get("/dashboard", response_model=WorkflowDashboardResponse)
def get_workflow_dashboard(
    session: Annotated[Session, Depends(get_session)],
    source: str | None = None,
    shop: int | None = None,
    category_id: Annotated[int | None, Query(gt=0)] = None,
    q: str | None = None,
) -> WorkflowDashboardResponse:
    dashboard = CatalogWorkflowQueueCatalog(session).dashboard(
        CatalogWorkflowQueueFilters(
            source=source,
            shop_id=shop,
            category_id=category_id,
            q=q,
            limit=1,
            offset=0,
        )
    )
    return WorkflowDashboardResponse(
        counts=tuple(
            WorkflowDashboardCountResponse.model_validate(item)
            for item in dashboard.counts
        )
    )


@router.get("/queues/{queue}", response_model=WorkflowQueueResponse)
def list_workflow_queue(
    queue: Annotated[CatalogWorkflowQueueName, Path()],
    session: Annotated[Session, Depends(get_session)],
    source: str | None = None,
    shop: int | None = None,
    category_id: Annotated[int | None, Query(gt=0)] = None,
    q: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> WorkflowQueueResponse:
    page = CatalogWorkflowQueueCatalog(session).list_queue(
        queue,
        CatalogWorkflowQueueFilters(
            source=source,
            shop_id=shop,
            category_id=category_id,
            q=q,
            limit=limit,
            offset=offset,
        ),
    )
    return WorkflowQueueResponse(
        queue=page.queue,
        items=tuple(WorkflowQueueItemResponse.model_validate(item) for item in page.items),
        limit=page.limit,
        offset=page.offset,
        total=page.total,
    )


@router.post("/batches/auto-accept", response_model=WorkflowAutoAcceptResponse)
def auto_accept_workflow_items(
    payload: WorkflowAutoAcceptRequest,
    session: Annotated[Session, Depends(get_session)],
) -> WorkflowAutoAcceptResponse:
    result = CatalogWorkflowAutoAcceptService(session).run(
        CatalogWorkflowQueueFilters(
            source=payload.source,
            shop_id=payload.shop_id,
            category_id=payload.category_id,
            q=payload.q,
            limit=payload.limit,
            offset=payload.offset,
        ),
        dry_run=payload.dry_run,
        actor=payload.actor,
        reason=payload.reason,
    )
    if not payload.dry_run:
        session.commit()
    return WorkflowAutoAcceptResponse.model_validate(result)
