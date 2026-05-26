from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session
from stroyhub.db import get_session
from stroyhub.db.repositories import OperatorDecisionFilters, OperatorDecisionRepository
from stroyhub.ml.operator_decisions import (
    OperatorDecisionDatasetBuilder,
    export_operator_decisions_jsonl,
)
from stroyhub.models.tables import OperatorDecision

router = APIRouter(prefix="/operator-decisions", tags=["operator-decisions"])
OperatorDecisionType = Literal["categorization", "normalization", "data_quality"]


class OperatorDecisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    decision_type: str
    action: str
    entity_type: str
    entity_id: int | None
    source_product_id: int | None
    canonical_product_id: int | None
    product_match_id: int | None
    category_id: int | None
    actor: str | None
    reason: str | None
    previous_state: dict[str, Any] | None
    new_state: dict[str, Any] | None
    evidence: dict[str, Any] | None
    alternatives: dict[str, Any] | None
    metadata: dict[str, Any] | None
    decided_at: datetime


class OperatorDecisionSearchResponse(BaseModel):
    items: list[OperatorDecisionResponse]
    limit: int
    offset: int
    total: int


class CategoryDecisionExampleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source_product_id: int
    category_id: int
    candidate_category_ids: tuple[int, ...]
    actor: str | None
    decided_at: datetime
    evidence: dict[str, Any] | None
    alternatives: dict[str, Any] | None


class NormalizationDecisionExampleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source_product_id: int
    canonical_product_id: int
    product_match_id: int | None
    outcome: str
    action: str
    actor: str | None
    decided_at: datetime
    evidence: dict[str, Any] | None
    alternatives: dict[str, Any] | None


class CategoryDecisionDatasetResponse(BaseModel):
    items: list[CategoryDecisionExampleResponse]
    limit: int
    offset: int


class NormalizationDecisionDatasetResponse(BaseModel):
    items: list[NormalizationDecisionExampleResponse]
    limit: int
    offset: int


@router.get("", response_model=OperatorDecisionSearchResponse)
def list_operator_decisions(
    session: Annotated[Session, Depends(get_session)],
    decision_type: OperatorDecisionType | None = None,
    action: str | None = None,
    actor: str | None = None,
    source_product_id: Annotated[int | None, Query(gt=0)] = None,
    canonical_product_id: Annotated[int | None, Query(gt=0)] = None,
    product_match_id: Annotated[int | None, Query(gt=0)] = None,
    category_id: Annotated[int | None, Query(gt=0)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> OperatorDecisionSearchResponse:
    filters = _filters(
        decision_type=decision_type,
        action=action,
        actor=actor,
        source_product_id=source_product_id,
        canonical_product_id=canonical_product_id,
        product_match_id=product_match_id,
        category_id=category_id,
        limit=limit,
        offset=offset,
    )
    repository = OperatorDecisionRepository(session)
    return OperatorDecisionSearchResponse(
        items=[_decision_response(item) for item in repository.list(filters)],
        limit=limit,
        offset=offset,
        total=repository.count(filters),
    )


@router.get("/export")
def export_operator_decisions(
    session: Annotated[Session, Depends(get_session)],
    decision_type: OperatorDecisionType | None = None,
    action: str | None = None,
    actor: str | None = None,
    source_product_id: Annotated[int | None, Query(gt=0)] = None,
    canonical_product_id: Annotated[int | None, Query(gt=0)] = None,
    product_match_id: Annotated[int | None, Query(gt=0)] = None,
    category_id: Annotated[int | None, Query(gt=0)] = None,
    limit: Annotated[int, Query(ge=1, le=5000)] = 5000,
) -> Response:
    filters = _filters(
        decision_type=decision_type,
        action=action,
        actor=actor,
        source_product_id=source_product_id,
        canonical_product_id=canonical_product_id,
        product_match_id=product_match_id,
        category_id=category_id,
        limit=limit,
        offset=0,
    )
    decisions = OperatorDecisionRepository(session).list(filters)
    return Response(
        content=export_operator_decisions_jsonl(decisions),
        media_type="application/x-ndjson",
    )


@router.get("/datasets/category", response_model=CategoryDecisionDatasetResponse)
def category_decision_dataset(
    session: Annotated[Session, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CategoryDecisionDatasetResponse:
    items = OperatorDecisionDatasetBuilder(session).category_examples(
        limit=limit,
        offset=offset,
    )
    return CategoryDecisionDatasetResponse(
        items=[CategoryDecisionExampleResponse.model_validate(item) for item in items],
        limit=limit,
        offset=offset,
    )


@router.get(
    "/datasets/normalization",
    response_model=NormalizationDecisionDatasetResponse,
)
def normalization_decision_dataset(
    session: Annotated[Session, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> NormalizationDecisionDatasetResponse:
    items = OperatorDecisionDatasetBuilder(session).normalization_examples(
        limit=limit,
        offset=offset,
    )
    return NormalizationDecisionDatasetResponse(
        items=[
            NormalizationDecisionExampleResponse.model_validate(item)
            for item in items
        ],
        limit=limit,
        offset=offset,
    )


def _filters(
    *,
    decision_type: str | None,
    action: str | None,
    actor: str | None,
    source_product_id: int | None,
    canonical_product_id: int | None,
    product_match_id: int | None,
    category_id: int | None,
    limit: int,
    offset: int,
) -> OperatorDecisionFilters:
    return OperatorDecisionFilters(
        decision_type=decision_type,
        action=action,
        actor=actor,
        source_product_id=source_product_id,
        canonical_product_id=canonical_product_id,
        product_match_id=product_match_id,
        category_id=category_id,
        limit=limit,
        offset=offset,
    )


def _decision_response(decision: OperatorDecision) -> OperatorDecisionResponse:
    return OperatorDecisionResponse(
        id=decision.id,
        decision_type=decision.decision_type,
        action=decision.action,
        entity_type=decision.entity_type,
        entity_id=decision.entity_id,
        source_product_id=decision.source_product_id,
        canonical_product_id=decision.canonical_product_id,
        product_match_id=decision.product_match_id,
        category_id=decision.category_id,
        actor=decision.actor,
        reason=decision.reason,
        previous_state=decision.previous_state,
        new_state=decision.new_state,
        evidence=decision.evidence,
        alternatives=decision.alternatives,
        metadata=decision.decision_metadata,
        decided_at=decision.decided_at,
    )
