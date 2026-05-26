from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal, NoReturn

from fastapi import APIRouter, Depends, Path
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session
from stroyhub.catalog.product_match_auto_accept import (
    ProductMatchAutoAcceptFilters,
    ProductMatchAutoAcceptService,
)
from stroyhub.catalog.product_match_decisions import (
    ProductMatchDecisionConflict,
    ProductMatchDecisionInput,
    ProductMatchDecisionNotFound,
    ProductMatchDecisionService,
)
from stroyhub.catalog.product_match_generation import (
    ProductMatchCandidateGenerator,
    ProductMatchGenerationFilters,
)
from stroyhub.db import get_session

from apps.admin_api.errors import ApiError, api_error_responses
from apps.admin_api.validation import ActorName, ReasonText

router = APIRouter(prefix="/product-matches", tags=["product-matches"])
AutoAcceptMethod = Literal["exact_normalized_title", "exact_title"]


class ProductMatchDecisionRequest(BaseModel):
    canonical_product_id: Annotated[int, Field(gt=0)]
    source_product_id: Annotated[int, Field(gt=0)]
    actor: ActorName | None = "admin"
    reason: ReasonText | None = None


class ProductMatchGenerateCandidatesRequest(BaseModel):
    source: str | None = None
    shop_id: int | None = None
    category_id: int | None = None
    min_confidence: float = Field(default=0.75, ge=0, le=1)
    limit: int = Field(default=100, ge=1, le=1000)


class ProductMatchAutoAcceptRequest(BaseModel):
    source: str | None = None
    shop_id: int | None = Field(default=None, gt=0)
    category_id: int | None = Field(default=None, gt=0)
    q: str | None = None
    min_confidence: Decimal = Field(default=Decimal("1.000"), ge=0, le=1)
    methods: tuple[AutoAcceptMethod, ...] = ("exact_normalized_title",)
    limit: int = Field(default=100, ge=1, le=1000)
    dry_run: bool = True
    actor: ActorName | None = "admin"
    reason: ReasonText | None = None


class ProductMatchReviewRequest(BaseModel):
    actor: ActorName | None = "admin"
    reason: ReasonText | None = None


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


class ProductMatchGenerateCandidatesResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source_products_considered: int
    reference_products_considered: int
    candidates_seen: int
    candidates_created: int
    candidates_skipped_existing: int


class ProductMatchAutoAcceptItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    match_id: int
    canonical_product_id: int
    canonical_title: str
    source_product_id: int
    source_title: str
    confidence: Decimal
    method: str


class ProductMatchAutoAcceptResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    dry_run: bool
    candidates_seen: int
    would_accept: int
    accepted: int
    skipped_already_accepted: int
    skipped_ambiguous: int
    skipped_ineligible: int
    skipped_category_mismatch: int
    skipped_low_confidence: int
    skipped_method: int
    skipped_previously_rejected: int
    followup_candidates_created: int
    items: tuple[ProductMatchAutoAcceptItemResponse, ...]


@router.post("/generate-candidates", response_model=ProductMatchGenerateCandidatesResponse)
def generate_product_match_candidates(
    payload: ProductMatchGenerateCandidatesRequest,
    session: Annotated[Session, Depends(get_session)],
) -> ProductMatchGenerateCandidatesResponse:
    result = ProductMatchCandidateGenerator(session).generate(
        ProductMatchGenerationFilters(
            source=payload.source,
            shop_id=payload.shop_id,
            category_id=payload.category_id,
            min_confidence=payload.min_confidence,
            limit=payload.limit,
        )
    )
    session.commit()
    return ProductMatchGenerateCandidatesResponse.model_validate(result)


@router.post("/auto-accept-candidates", response_model=ProductMatchAutoAcceptResponse)
def auto_accept_product_match_candidates(
    payload: ProductMatchAutoAcceptRequest,
    session: Annotated[Session, Depends(get_session)],
) -> ProductMatchAutoAcceptResponse:
    result = ProductMatchAutoAcceptService(session).run(
        ProductMatchAutoAcceptFilters(
            source=payload.source,
            shop_id=payload.shop_id,
            category_id=payload.category_id,
            q=payload.q,
            min_confidence=payload.min_confidence,
            methods=tuple(payload.methods),
            limit=payload.limit,
            dry_run=payload.dry_run,
            actor=payload.actor,
            reason=payload.reason,
        )
    )
    if not payload.dry_run:
        session.commit()
    return ProductMatchAutoAcceptResponse.model_validate(result)


@router.post(
    "/accept",
    response_model=ProductMatchDecisionResponse,
    responses=api_error_responses(404, 409),
)
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


@router.post(
    "/supersede",
    response_model=ProductMatchDecisionResponse,
    responses=api_error_responses(404, 409),
)
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
    responses=api_error_responses(404, 409),
)
def create_canonical_from_source_and_accept(
    source_product_id: Annotated[int, Path(gt=0)],
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


@router.post(
    "/{match_id}/reject",
    response_model=ProductMatchDecisionResponse,
    responses=api_error_responses(404, 409),
)
def reject_product_match(
    match_id: Annotated[int, Path(gt=0)],
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
        message = str(exc)
        raise ApiError(
            status_code=404,
            code=_not_found_code(message),
            message=message,
        ) from exc
    raise ApiError(
        status_code=409,
        code="product_match_conflict",
        message=str(exc),
    ) from exc


def _not_found_code(message: str) -> str:
    if message == "Canonical product not found":
        return "canonical_product_not_found"
    if message == "Source product not found":
        return "source_product_not_found"
    return "product_match_not_found"
