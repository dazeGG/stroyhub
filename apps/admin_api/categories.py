from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session
from stroyhub.catalog.categories import CategoryCatalog, CategoryPriceSummaryFilters
from stroyhub.catalog.category_quality import CategoryQualityCatalog, CategoryQualityFilters
from stroyhub.catalog.source_category_mappings import (
    SourceCategoryMappingCatalog,
    SourceCategoryMappingFilters,
)
from stroyhub.db import get_session
from stroyhub.db.repositories import (
    SourceCategoryMappingRepository,
    SourceCategoryMappingUpsert,
)

from apps.admin_api.validation import ActorName, ReasonText

router = APIRouter(prefix="/categories", tags=["categories"])


class CategoryTreeItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    name: str
    parent_id: int | None
    product_count: int
    children: list["CategoryTreeItemResponse"]


class CategoryTreeResponse(BaseModel):
    items: list[CategoryTreeItemResponse]


class CategoryPriceSummaryItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    category_id: int | None
    category_slug: str | None
    category_name: str | None
    product_count: int
    priced_product_count: int
    min_price: Decimal | None
    avg_price: Decimal | None
    max_price: Decimal | None


class CategoryPriceSummaryResponse(BaseModel):
    items: list[CategoryPriceSummaryItemResponse]


class UncategorizedCategoryGroupResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source: str
    shop_id: int
    shop_name: str
    shop_source_id: str
    category_raw: str | None
    count: int
    titles: tuple[str, ...]


class CategoryQualityResponse(BaseModel):
    total_products: int
    categorized_products: int
    uncategorized_products: int
    coverage_pct: Decimal
    groups: list[UncategorizedCategoryGroupResponse]


class SourceCategoryMappingCategoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int | None
    slug: str | None
    name: str | None


class SourceCategoryMappingItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source: str
    raw_category: str | None
    normalized_raw_category: str
    product_count: int
    categorized_product_count: int
    uncategorized_product_count: int
    mapping_id: int | None
    mapping_origin: str
    mapping_status: str
    category: SourceCategoryMappingCategoryResponse | None
    confidence: Decimal | None
    reason: str | None
    examples: tuple[str, ...]


class SourceCategoryMappingResponse(BaseModel):
    items: list[SourceCategoryMappingItemResponse]
    limit: int
    offset: int
    total: int


class SourceCategoryMappingUpsertRequest(BaseModel):
    source: str = Field(min_length=1, max_length=80)
    raw_category: str = Field(min_length=1, max_length=240)
    category_id: int | None = Field(default=None, gt=0)
    status: Literal["active", "non_product", "disabled"] = "active"
    confidence: Decimal = Field(default=Decimal("1.000"), ge=0, le=1)
    actor: ActorName | None = "admin"
    reason: ReasonText | None = None


class SourceCategoryMappingUpsertResponse(BaseModel):
    id: int
    source: str
    raw_category: str
    normalized_raw_category: str
    category_id: int | None
    status: str
    confidence: Decimal
    reason: str | None
    created_by: str | None
    updated_by: str | None


@router.get("", response_model=CategoryTreeResponse)
def list_categories(
    session: Annotated[Session, Depends(get_session)],
) -> CategoryTreeResponse:
    items = [
        CategoryTreeItemResponse.model_validate(item)
        for item in CategoryCatalog(session).list_tree()
    ]
    return CategoryTreeResponse(items=items)


@router.get("/price-summary", response_model=CategoryPriceSummaryResponse)
def list_category_price_summary(
    session: Annotated[Session, Depends(get_session)],
    source: str | None = None,
    shop: int | None = None,
) -> CategoryPriceSummaryResponse:
    filters = CategoryPriceSummaryFilters(source=source, shop_id=shop)
    items = [
        CategoryPriceSummaryItemResponse.model_validate(item)
        for item in CategoryCatalog(session).list_price_summary(filters)
    ]
    return CategoryPriceSummaryResponse(items=items)


@router.get("/quality", response_model=CategoryQualityResponse)
def get_category_quality(
    session: Annotated[Session, Depends(get_session)],
    source: str | None = None,
    shop: int | None = None,
    limit_groups: Annotated[int, Query(ge=1, le=100)] = 50,
    titles_per_group: Annotated[int, Query(ge=1, le=10)] = 3,
) -> CategoryQualityResponse:
    filters = CategoryQualityFilters(
        source=source,
        shop_id=shop,
        limit_groups=limit_groups,
        titles_per_group=titles_per_group,
    )
    quality = CategoryQualityCatalog(session).get_quality(filters)
    return CategoryQualityResponse(
        total_products=quality.total_products,
        categorized_products=quality.categorized_products,
        uncategorized_products=quality.uncategorized_products,
        coverage_pct=quality.coverage_pct,
        groups=[
            UncategorizedCategoryGroupResponse.model_validate(group)
            for group in quality.groups
        ],
    )


@router.get("/source-mappings", response_model=SourceCategoryMappingResponse)
def list_source_category_mappings(
    session: Annotated[Session, Depends(get_session)],
    source: str | None = None,
    q: str | None = None,
    status: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    examples_per_group: Annotated[int, Query(ge=0, le=10)] = 3,
) -> SourceCategoryMappingResponse:
    page = SourceCategoryMappingCatalog(session).list_mappings(
        SourceCategoryMappingFilters(
            source=source,
            q=q,
            status=status,
            limit=limit,
            offset=offset,
            examples_per_group=examples_per_group,
        )
    )
    return SourceCategoryMappingResponse(
        items=[
            SourceCategoryMappingItemResponse.model_validate(item)
            for item in page.items
        ],
        limit=page.limit,
        offset=page.offset,
        total=page.total,
    )


@router.put("/source-mappings", response_model=SourceCategoryMappingUpsertResponse)
def upsert_source_category_mapping(
    payload: SourceCategoryMappingUpsertRequest,
    session: Annotated[Session, Depends(get_session)],
) -> SourceCategoryMappingUpsertResponse:
    try:
        mapping = SourceCategoryMappingRepository(session).upsert(
            SourceCategoryMappingUpsert(
                source=payload.source,
                raw_category=payload.raw_category,
                category_id=payload.category_id,
                status=payload.status,
                confidence=payload.confidence,
                actor=payload.actor,
                reason=payload.reason,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    session.commit()
    return SourceCategoryMappingUpsertResponse(
        id=mapping.id,
        source=mapping.source,
        raw_category=mapping.raw_category,
        normalized_raw_category=mapping.normalized_raw_category,
        category_id=mapping.category_id,
        status=mapping.status,
        confidence=mapping.confidence,
        reason=mapping.reason,
        created_by=mapping.created_by,
        updated_by=mapping.updated_by,
    )
