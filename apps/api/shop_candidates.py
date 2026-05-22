from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session
from stroyhub.catalog.shop_candidates import (
    CandidateListFilters,
    CandidateRefreshSummary,
    ShopCandidateCatalog,
)
from stroyhub.db import get_session
from stroyhub.models import ShopSourceCandidate

router = APIRouter(prefix="/shop-source-candidates", tags=["shop-source-candidates"])


class ShopSourceCandidateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    source_id: str
    source_type: str
    display_name: str
    address: str | None
    website_url: str | None
    rubrics: str | None
    status: str
    has_products: bool
    has_prices: bool
    has_website: bool
    product_count: int
    priced_product_count: int
    priority: int
    priority_reason: str
    last_seen_at: datetime | None
    last_checked_at: datetime | None
    missing_since: datetime | None
    approved_shop_id: int | None
    official_strategy: dict[str, object] | None = None
    suggested_identity: dict[str, object] | None = None


class ShopSourceCandidateApproveRequest(BaseModel):
    shop_identity_id: int | None = None


class ShopSourceCandidateListResponse(BaseModel):
    items: list[ShopSourceCandidateResponse]


class ShopSourceCandidateRefreshResponse(BaseModel):
    checked: int
    created: int
    updated: int
    stale: int
    skipped_approved: int
    items: list[ShopSourceCandidateResponse]


@router.get("", response_model=ShopSourceCandidateListResponse)
def list_shop_source_candidates(
    session: Annotated[Session, Depends(get_session)],
    status: str | None = None,
    include_approved: bool = False,
) -> ShopSourceCandidateListResponse:
    catalog = ShopCandidateCatalog(session)
    try:
        items = catalog.list_candidates(
            CandidateListFilters(status=status, include_approved=include_approved)
        )
    except ValueError as exc:
        raise _http_error(exc) from exc

    return ShopSourceCandidateListResponse(
        items=[_candidate_response_model(item, catalog) for item in items]
    )


@router.post("/refresh", response_model=ShopSourceCandidateRefreshResponse)
def refresh_shop_source_candidates(
    session: Annotated[Session, Depends(get_session)],
) -> ShopSourceCandidateRefreshResponse:
    catalog = ShopCandidateCatalog(session)
    summary = catalog.refresh_from_twogis()
    session.commit()
    session.expire_all()
    items = catalog.list_candidates(CandidateListFilters())
    return _refresh_response(summary, items, catalog)


@router.post("/{candidate_id}/approve", response_model=ShopSourceCandidateResponse)
def approve_shop_source_candidate(
    candidate_id: int,
    session: Annotated[Session, Depends(get_session)],
    payload: ShopSourceCandidateApproveRequest | None = None,
) -> ShopSourceCandidateResponse:
    catalog = ShopCandidateCatalog(session)
    try:
        candidate = catalog.approve(
            candidate_id,
            shop_identity_id=payload.shop_identity_id if payload is not None else None,
        )
    except ValueError as exc:
        raise _http_error(exc) from exc

    approved_candidate_id = candidate.id
    session.commit()
    session.expire_all()
    return _candidate_response(approved_candidate_id, session)


def _refresh_response(
    summary: CandidateRefreshSummary,
    items: list[ShopSourceCandidate],
    catalog: ShopCandidateCatalog,
) -> ShopSourceCandidateRefreshResponse:
    return ShopSourceCandidateRefreshResponse(
        checked=summary.checked,
        created=summary.created,
        updated=summary.updated,
        stale=summary.stale,
        skipped_approved=summary.skipped_approved,
        items=[_candidate_response_model(item, catalog) for item in items],
    )


def _candidate_response(
    candidate_id: int,
    session: Session,
) -> ShopSourceCandidateResponse:
    catalog = ShopCandidateCatalog(session)
    for item in catalog.list_candidates(
        CandidateListFilters(include_approved=True)
    ):
        if item.id == candidate_id:
            return _candidate_response_model(item, catalog)
    raise HTTPException(status_code=404, detail="shop source candidate not found")


def _candidate_response_model(
    candidate: ShopSourceCandidate,
    catalog: ShopCandidateCatalog,
) -> ShopSourceCandidateResponse:
    response = ShopSourceCandidateResponse.model_validate(candidate)
    if isinstance(candidate.raw, dict):
        strategy = candidate.raw.get("official_strategy")
        if isinstance(strategy, dict):
            response.official_strategy = strategy
    suggestion = catalog.suggest_identity(candidate)
    if suggestion is not None:
        response.suggested_identity = {
            "id": suggestion.id,
            "display_name": suggestion.display_name,
            "status": suggestion.status,
            "source_count": suggestion.source_count,
            "reason": suggestion.reason,
        }
    return response


def _http_error(error: ValueError) -> HTTPException:
    detail = str(error)
    if "not found" in detail:
        return HTTPException(status_code=404, detail=detail)
    return HTTPException(status_code=400, detail=detail)
