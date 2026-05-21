from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session
from stroyhub.catalog.products import ProductCatalog, ProductSearchFilters, ProductSort
from stroyhub.db import get_session
from stroyhub.db.repositories import (
    CategoryOverrideCreate,
    CategoryOverrideRepository,
    CategoryOverrideRevert,
    CategoryRepository,
)

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
    category_id: int
    reason: str | None = None
    actor: str | None = "admin"


@router.get("", response_model=ProductSearchResponse)
def search_products(
    session: Annotated[Session, Depends(get_session)],
    q: str | None = None,
    category: int | None = None,
    category_id: int | None = None,
    category_slug: str | None = None,
    shop: int | None = None,
    sort: ProductSort = "-last_seen_at",
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ProductSearchResponse:
    filters = ProductSearchFilters(
        q=q,
        category_id=category_id if category_id is not None else category,
        category_slug=category_slug,
        shop_id=shop,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    items = [
        ProductSearchItemResponse.model_validate(item)
        for item in ProductCatalog(session).search_products(filters)
    ]
    return ProductSearchResponse(items=items, limit=limit, offset=offset)


@router.get("/{product_id}", response_model=ProductSearchItemResponse)
def get_product(
    product_id: int,
    session: Annotated[Session, Depends(get_session)],
) -> ProductSearchItemResponse:
    item = ProductCatalog(session).get_product(product_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Source product not found")

    return ProductSearchItemResponse.model_validate(item)


@router.put("/{product_id}/category-override", response_model=ProductSearchItemResponse)
def assign_product_category_override(
    product_id: int,
    payload: ProductCategoryOverrideRequest,
    session: Annotated[Session, Depends(get_session)],
) -> ProductSearchItemResponse:
    catalog = ProductCatalog(session)
    if catalog.get_product(product_id) is None:
        raise HTTPException(status_code=404, detail="Source product not found")

    category_repository = CategoryRepository(session)
    if category_repository.get(payload.category_id) is None:
        raise HTTPException(status_code=404, detail="Category not found")
    if category_repository.has_children(payload.category_id):
        raise HTTPException(status_code=422, detail="Category override must target a leaf category")

    CategoryOverrideRepository(session).create_or_replace(
        CategoryOverrideCreate(
            source_product_id=product_id,
            category_id=payload.category_id,
            reason=payload.reason,
            actor=payload.actor,
        )
    )
    session.commit()

    item = ProductCatalog(session).get_product(product_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Source product not found")
    return ProductSearchItemResponse.model_validate(item)


@router.delete("/{product_id}/category-override", response_model=ProductSearchItemResponse)
def revert_product_category_override(
    product_id: int,
    session: Annotated[Session, Depends(get_session)],
    actor: str | None = "admin",
) -> ProductSearchItemResponse:
    catalog = ProductCatalog(session)
    if catalog.get_product(product_id) is None:
        raise HTTPException(status_code=404, detail="Source product not found")

    reverted = CategoryOverrideRepository(session).revert_active(
        CategoryOverrideRevert(source_product_id=product_id, actor=actor)
    )
    if reverted is None:
        raise HTTPException(status_code=404, detail="Active category override not found")

    session.commit()

    item = ProductCatalog(session).get_product(product_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Source product not found")
    return ProductSearchItemResponse.model_validate(item)


@router.get("/{product_id}/prices", response_model=ProductPriceHistoryResponse)
def list_product_prices(
    product_id: int,
    session: Annotated[Session, Depends(get_session)],
) -> ProductPriceHistoryResponse:
    catalog = ProductCatalog(session)
    if not catalog.source_product_exists(product_id):
        raise HTTPException(status_code=404, detail="Source product not found")

    items = [
        ProductPriceSnapshotResponse.model_validate(item)
        for item in catalog.list_price_history(product_id)
    ]
    return ProductPriceHistoryResponse(product_id=product_id, items=items)
