from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session
from stroyhub.catalog.match_candidates import MatchCandidateCatalog, MatchCandidateFilters
from stroyhub.db import get_session

router = APIRouter(prefix="/matches", tags=["matches"])


class MatchCandidateProductResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    shop_id: int
    shop_name: str
    shop_source_id: str
    title: str
    normalized_title: str
    category_id: int | None
    category_raw: str | None


class MatchCandidateReasonResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    method: str
    exact_title: bool
    matched_normalized_title: str | None
    token_overlap: tuple[str, ...]
    left_only_tokens: tuple[str, ...]
    right_only_tokens: tuple[str, ...]
    ignored_tokens: tuple[str, ...]
    blocked_by: tuple[str, ...]
    token_similarity: float
    same_category: bool | None


class MatchCandidatePairResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    left: MatchCandidateProductResponse
    right: MatchCandidateProductResponse
    confidence: float
    reason: MatchCandidateReasonResponse


class MatchCandidateResponse(BaseModel):
    products_considered: int
    candidates: list[MatchCandidatePairResponse]


@router.get("/candidates", response_model=MatchCandidateResponse)
def list_match_candidates(
    session: Annotated[Session, Depends(get_session)],
    source: str | None = None,
    shop: int | None = None,
    category_id: int | None = None,
    category_raw: str | None = None,
    min_confidence: Annotated[float, Query(ge=0, le=1)] = 0.75,
    max_confidence: Annotated[float | None, Query(ge=0, le=1)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    allow_category_mismatch: bool = False,
) -> MatchCandidateResponse:
    filters = MatchCandidateFilters(
        source=source,
        shop_id=shop,
        category_id=category_id,
        category_raw=category_raw,
        min_confidence=min_confidence,
        max_confidence=max_confidence,
        limit=limit,
        allow_category_mismatch=allow_category_mismatch,
    )
    report = MatchCandidateCatalog(session).list_candidates(filters)
    return MatchCandidateResponse(
        products_considered=report.products_considered,
        candidates=[
            MatchCandidatePairResponse.model_validate(candidate)
            for candidate in report.candidates
        ],
    )
