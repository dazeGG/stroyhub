from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session
from stroyhub.catalog.patron_review import (
    PatronReviewAction,
    PatronReviewMode,
    PatronReviewQueue,
)
from stroyhub.catalog.quality_pipeline import CatalogQualityPipeline
from stroyhub.db import get_session
from stroyhub.models import SourceProduct

from apps.admin_api.errors import ApiError, api_error_responses
from apps.admin_api.validation import ActorName, ReasonText

router = APIRouter(prefix="/patron-review", tags=["patron-review"])


class PatronReviewShopResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    source_id: str
    name: str


class PatronReviewCategoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    name: str


class PatronReviewLatestPriceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    price: Decimal | None
    price_kind: str
    price_text: str | None
    currency: str
    unit_raw: str | None
    source_updated_at: datetime | None
    parsed_at: datetime


class PatronReviewItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    source_product_id: str | None
    title: str
    normalized_title: str
    description: str | None
    category_id: int | None
    category: PatronReviewCategoryResponse | None
    category_raw: str | None
    unit_raw: str | None
    image_url: str | None
    source_updated_at: datetime | None
    last_seen_at: datetime
    is_not_product: bool
    shop: PatronReviewShopResponse
    latest_price: PatronReviewLatestPriceResponse | None
    catalog_eligibility: dict[str, object] | None
    raw: dict[str, object] | None


class PatronReviewStatsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    total: int
    remaining: int
    reviewed: int
    skipped: int


class PatronReviewPageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    item: PatronReviewItemResponse | None
    stats: PatronReviewStatsResponse


class PatronReviewDecisionRequest(BaseModel):
    action: PatronReviewAction
    actor: ActorName | None = "admin"
    reason: ReasonText | None = None


class PatronReviewUndoRequest(BaseModel):
    actor: ActorName | None = "admin"
    reason: ReasonText | None = None


class PatronReviewDecisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    action: Literal["product", "not_product", "skip", "undo"]
    product_id: int | None
    stats: PatronReviewStatsResponse


@router.get("", response_model=PatronReviewPageResponse)
def get_patron_review_item(
    session: Annotated[Session, Depends(get_session)],
    mode: Annotated[PatronReviewMode, Query()] = "needs_review",
    min_probability: Annotated[Decimal, Query(ge=Decimal("0.000"), le=Decimal("1.000"))] = Decimal(
        "0.700"
    ),
) -> PatronReviewPageResponse:
    page = PatronReviewQueue(
        session,
        mode=mode,
        min_probability=min_probability,
    ).current()
    return PatronReviewPageResponse.model_validate(page)


@router.post(
    "/{product_id}/decision",
    response_model=PatronReviewDecisionResponse,
    responses=api_error_responses(404),
)
def decide_patron_review_item(
    product_id: Annotated[int, Path(gt=0)],
    payload: PatronReviewDecisionRequest,
    session: Annotated[Session, Depends(get_session)],
    mode: Annotated[PatronReviewMode, Query()] = "needs_review",
    min_probability: Annotated[Decimal, Query(ge=Decimal("0.000"), le=Decimal("1.000"))] = Decimal(
        "0.700"
    ),
) -> PatronReviewDecisionResponse:
    try:
        result = PatronReviewQueue(
            session,
            mode=mode,
            min_probability=min_probability,
        ).decide(
            product_id=product_id,
            action=payload.action,
            actor=payload.actor,
            reason=payload.reason,
        )
    except ValueError as error:
        raise ApiError(
            status_code=404,
            code="patron_review_item_not_found",
            message=str(error),
        ) from error
    if result.product_id is not None and payload.action in {"product", "not_product"}:
        _refresh_product_quality(session, result.product_id)
    session.commit()
    return PatronReviewDecisionResponse.model_validate(result)


@router.post(
    "/undo",
    response_model=PatronReviewDecisionResponse,
    responses=api_error_responses(404),
)
def undo_patron_review_decision(
    payload: PatronReviewUndoRequest,
    session: Annotated[Session, Depends(get_session)],
    mode: Annotated[PatronReviewMode, Query()] = "needs_review",
    min_probability: Annotated[Decimal, Query(ge=Decimal("0.000"), le=Decimal("1.000"))] = Decimal(
        "0.700"
    ),
) -> PatronReviewDecisionResponse:
    try:
        result = PatronReviewQueue(
            session,
            mode=mode,
            min_probability=min_probability,
        ).undo(
            actor=payload.actor,
            reason=payload.reason,
        )
    except ValueError as error:
        raise ApiError(
            status_code=404,
            code="patron_review_history_empty",
            message=str(error),
        ) from error
    if result.product_id is not None:
        _refresh_product_quality(session, result.product_id)
    session.commit()
    return PatronReviewDecisionResponse.model_validate(result)


def _refresh_product_quality(session: Session, product_id: int) -> None:
    product = session.get(SourceProduct, product_id)
    if product is None:
        return
    CatalogQualityPipeline(session).run_for_shop(product.shop_id)
