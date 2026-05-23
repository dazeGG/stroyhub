from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, NoReturn

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session
from stroyhub.catalog.product_match_decisions import (
    ProductMatchDecisionConflict,
    ProductMatchDecisionInput,
    ProductMatchDecisionNotFound,
    ProductMatchDecisionService,
)
from stroyhub.db import get_session

router = APIRouter(prefix="/product-matches", tags=["product-matches"])


class ProductMatchDecisionRequest(BaseModel):
    canonical_product_id: int
    source_product_id: int
    actor: str | None = "admin"
    reason: str | None = None


class ProductMatchReviewRequest(BaseModel):
    actor: str | None = "admin"
    reason: str | None = None


class ProductMatchDecisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    canonical_product_id: int
    source_product_id: int
    confidence: Decimal
    status: str
    method: str
    matched_at: datetime
    reviewed_at: datetime | None
    reviewed_by: str | None
    reason: dict[str, Any] | None


@router.post("/accept", response_model=ProductMatchDecisionResponse)
def accept_product_match(
    payload: ProductMatchDecisionRequest,
    session: Annotated[Session, Depends(get_session)],
) -> ProductMatchDecisionResponse:
    try:
        decision = _service(session).accept_existing(
            canonical_product_id=payload.canonical_product_id,
            source_product_id=payload.source_product_id,
            data=ProductMatchDecisionInput(actor=payload.actor, reason=payload.reason),
        )
    except (ProductMatchDecisionNotFound, ProductMatchDecisionConflict) as exc:
        _handle_decision_error(exc)
    session.commit()
    return ProductMatchDecisionResponse.model_validate(decision)


@router.post("/supersede", response_model=ProductMatchDecisionResponse)
def supersede_product_match(
    payload: ProductMatchDecisionRequest,
    session: Annotated[Session, Depends(get_session)],
) -> ProductMatchDecisionResponse:
    try:
        decision = _service(session).supersede_existing(
            canonical_product_id=payload.canonical_product_id,
            source_product_id=payload.source_product_id,
            data=ProductMatchDecisionInput(actor=payload.actor, reason=payload.reason),
        )
    except (ProductMatchDecisionNotFound, ProductMatchDecisionConflict) as exc:
        _handle_decision_error(exc)
    session.commit()
    return ProductMatchDecisionResponse.model_validate(decision)


@router.post(
    "/from-source/{source_product_id}/accept",
    response_model=ProductMatchDecisionResponse,
    status_code=201,
)
def create_canonical_from_source_and_accept(
    source_product_id: int,
    payload: ProductMatchReviewRequest,
    session: Annotated[Session, Depends(get_session)],
) -> ProductMatchDecisionResponse:
    try:
        decision = _service(session).create_canonical_from_source_and_accept(
            source_product_id=source_product_id,
            data=ProductMatchDecisionInput(actor=payload.actor, reason=payload.reason),
        )
    except (ProductMatchDecisionNotFound, ProductMatchDecisionConflict) as exc:
        _handle_decision_error(exc)
    session.commit()
    return ProductMatchDecisionResponse.model_validate(decision)


@router.post("/{match_id}/reject", response_model=ProductMatchDecisionResponse)
def reject_product_match(
    match_id: int,
    payload: ProductMatchReviewRequest,
    session: Annotated[Session, Depends(get_session)],
) -> ProductMatchDecisionResponse:
    try:
        decision = _service(session).reject_candidate(
            match_id=match_id,
            data=ProductMatchDecisionInput(actor=payload.actor, reason=payload.reason),
        )
    except (ProductMatchDecisionNotFound, ProductMatchDecisionConflict) as exc:
        _handle_decision_error(exc)
    session.commit()
    return ProductMatchDecisionResponse.model_validate(decision)


def _service(session: Session) -> ProductMatchDecisionService:
    return ProductMatchDecisionService(session)


def _handle_decision_error(
    exc: ProductMatchDecisionNotFound | ProductMatchDecisionConflict,
) -> NoReturn:
    if isinstance(exc, ProductMatchDecisionNotFound):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    raise HTTPException(status_code=409, detail=str(exc)) from exc
