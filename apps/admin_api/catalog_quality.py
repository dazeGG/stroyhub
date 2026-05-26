from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session
from stroyhub.catalog.quality_checks import (
    CatalogQualityCheckFilters,
    CatalogQualityCheckService,
    CatalogQualitySeverity,
)
from stroyhub.db import get_session
from stroyhub.parsers.common import JsonObject

router = APIRouter(prefix="/catalog-quality", tags=["catalog-quality"])


class CatalogQualityFindingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    severity: CatalogQualitySeverity
    reason: str
    recommended_action: str
    source_product_id: int | None
    canonical_product_id: int | None
    shop_id: int | None
    related_source_product_ids: tuple[int, ...]
    related_canonical_product_ids: tuple[int, ...]
    metadata: JsonObject | None


class CatalogQualityFindingPageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    items: tuple[CatalogQualityFindingResponse, ...]
    total: int
    limit: int
    offset: int


class CatalogQualitySummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    total: int
    blockers: int
    warnings: int
    by_code: dict[str, int]


class CatalogQualityReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    summary: CatalogQualitySummaryResponse
    findings: CatalogQualityFindingPageResponse


@router.get("/findings", response_model=CatalogQualityReportResponse)
def list_catalog_quality_findings(
    session: Annotated[Session, Depends(get_session)],
    severity: CatalogQualitySeverity | None = None,
    code: str | None = None,
    stale_price_days: Annotated[int, Query(ge=1, le=365)] = 30,
    stale_shop_days: Annotated[int, Query(ge=1, le=365)] = 7,
    low_category_confidence: Annotated[Decimal, Query(ge=0, le=1)] = Decimal("0.750"),
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CatalogQualityReportResponse:
    report = CatalogQualityCheckService(
        session,
        stale_price_after_days=stale_price_days,
        stale_shop_after_days=stale_shop_days,
        low_category_confidence=low_category_confidence,
    ).report(
        CatalogQualityCheckFilters(
            severity=severity,
            code=code,
            limit=limit,
            offset=offset,
        )
    )
    return CatalogQualityReportResponse.model_validate(report)
