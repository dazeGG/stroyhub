from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session
from stroyhub.catalog.products import ProductCatalog, ProductSearchFilters, ProductSort
from stroyhub.catalog.quality_pipeline import CatalogQualityPipeline
from stroyhub.db import get_session
from stroyhub.db.repositories import (
    CategoryOverrideCreate,
    CategoryOverrideRepository,
    CategoryOverrideRevert,
    CategoryRepository,
)
from stroyhub.models import SourceProduct

from apps.admin_api.errors import ApiError, api_error_responses
from apps.admin_api.validation import ActorName, ReasonText

router = APIRouter(prefix="/products", tags=["products"])


class ProductShopResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    source_id: str
    name: str


class ProductLatestPriceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    price: Decimal | None
    currency: str
    unit_raw: str | None
    source_updated_at: datetime | None
    parsed_at: datetime


class ProductCategoryOverrideResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    category_id: int
    previous_category_id: int | None
    reason: str | None
    status: str
    created_by: str | None
    created_at: datetime
    updated_by: str | None
    updated_at: datetime
    deactivated_by: str | None
    deactivated_at: datetime | None


class ProductSearchItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    source_product_id: str | None
    title: str
    normalized_title: str
    description: str | None
    category_id: int | None
    category_raw: str | None
    unit_raw: str | None
    image_url: str | None
    source_updated_at: datetime | None
    last_seen_at: datetime
    shop: ProductShopResponse
    latest_price: ProductLatestPriceResponse | None
    category_override: ProductCategoryOverrideResponse | None


class ProductSearchResponse(BaseModel):
    items: list[ProductSearchItemResponse]
    limit: int
    offset: int
    total: int


class ProductPriceSnapshotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    price: Decimal | None
    currency: str
    unit_raw: str | None
    source_updated_at: datetime | None
    parsed_at: datetime


class ProductPriceHistoryResponse(BaseModel):
    product_id: int
    items: list[ProductPriceSnapshotResponse]


class ProductCategoryOverrideRequest(BaseModel):
    category_id: Annotated[int, Field(gt=0)]
    reason: ReasonText | None = None
    actor: ActorName | None = "admin"


@router.get("", response_model=ProductSearchResponse)
def search_products(
    session: Annotated[Session, Depends(get_session)],
    q: str | None = None,
    category: Annotated[int | None, Query(gt=0)] = None,
    category_id: Annotated[int | None, Query(gt=0)] = None,
    category_slug: str | None = None,
    uncategorized: bool = False,
    shop: Annotated[int | None, Query(gt=0)] = None,
    sort: ProductSort = "-last_seen_at",
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ProductSearchResponse:
    filters = ProductSearchFilters(
        q=q,
        category_id=category_id if category_id is not None else category,
        category_slug=category_slug,
        uncategorized=uncategorized,
        shop_id=shop,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    catalog = ProductCatalog(session)
    items = [
        ProductSearchItemResponse.model_validate(item)
        for item in catalog.search_products(filters)
    ]
    return ProductSearchResponse(
        items=items,
        limit=limit,
        offset=offset,
        total=catalog.count_products(filters),
    )


@router.get(
    "/{product_id}",
    response_model=ProductSearchItemResponse,
    responses=api_error_responses(404),
)
def get_product(
    product_id: Annotated[int, Path(gt=0)],
    session: Annotated[Session, Depends(get_session)],
) -> ProductSearchItemResponse:
    item = ProductCatalog(session).get_product(product_id)
    if item is None:
        raise ApiError(
            status_code=404,
            code="source_product_not_found",
            message="Source product not found",
        )

    return ProductSearchItemResponse.model_validate(item)


@router.put(
    "/{product_id}/category-override",
    response_model=ProductSearchItemResponse,
    responses=api_error_responses(404, 422),
)
def assign_product_category_override(
    product_id: Annotated[int, Path(gt=0)],
    payload: ProductCategoryOverrideRequest,
    session: Annotated[Session, Depends(get_session)],
) -> ProductSearchItemResponse:
    catalog = ProductCatalog(session)
    if catalog.get_product(product_id) is None:
        raise ApiError(
            status_code=404,
            code="source_product_not_found",
            message="Source product not found",
        )

    category_repository = CategoryRepository(session)
    if category_repository.get(payload.category_id) is None:
        raise ApiError(status_code=404, code="category_not_found", message="Category not found")
    if category_repository.has_children(payload.category_id):
        raise ApiError(
            status_code=422,
            code="category_override_requires_leaf",
            message="Category override must target a leaf category",
        )

    CategoryOverrideRepository(session).create_or_replace(
        CategoryOverrideCreate(
            source_product_id=product_id,
            category_id=payload.category_id,
            reason=payload.reason,
            actor=payload.actor,
        )
    )
    _refresh_product_quality(session, product_id)
    session.commit()

    item = ProductCatalog(session).get_product(product_id)
    if item is None:
        raise ApiError(
            status_code=404,
            code="source_product_not_found",
            message="Source product not found",
        )
    return ProductSearchItemResponse.model_validate(item)


@router.delete(
    "/{product_id}/category-override",
    response_model=ProductSearchItemResponse,
    responses=api_error_responses(404),
)
def revert_product_category_override(
    product_id: Annotated[int, Path(gt=0)],
    session: Annotated[Session, Depends(get_session)],
    actor: ActorName | None = "admin",
) -> ProductSearchItemResponse:
    catalog = ProductCatalog(session)
    if catalog.get_product(product_id) is None:
        raise ApiError(
            status_code=404,
            code="source_product_not_found",
            message="Source product not found",
        )

    reverted = CategoryOverrideRepository(session).revert_active(
        CategoryOverrideRevert(source_product_id=product_id, actor=actor)
    )
    if reverted is None:
        raise ApiError(
            status_code=404,
            code="active_category_override_not_found",
            message="Active category override not found",
        )

    _refresh_product_quality(session, product_id)
    session.commit()

    item = ProductCatalog(session).get_product(product_id)
    if item is None:
        raise ApiError(
            status_code=404,
            code="source_product_not_found",
            message="Source product not found",
        )
    return ProductSearchItemResponse.model_validate(item)


def _refresh_product_quality(session: Session, product_id: int) -> None:
    product = session.get(SourceProduct, product_id)
    if product is None:
        return
    CatalogQualityPipeline(session).run_for_shop(product.shop_id)


@router.get(
    "/{product_id}/prices",
    response_model=ProductPriceHistoryResponse,
    responses=api_error_responses(404),
)
def list_product_prices(
    product_id: Annotated[int, Path(gt=0)],
    session: Annotated[Session, Depends(get_session)],
) -> ProductPriceHistoryResponse:
    catalog = ProductCatalog(session)
    if not catalog.source_product_exists(product_id):
        raise ApiError(
            status_code=404,
            code="source_product_not_found",
            message="Source product not found",
        )

    items = [
        ProductPriceSnapshotResponse.model_validate(item)
        for item in catalog.list_price_history(product_id)
    ]
    return ProductPriceHistoryResponse(product_id=product_id, items=items)
