from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session
from stroyhub.catalog.products import ProductCatalog, ProductSearchFilters, ProductSort
from stroyhub.db import get_session

router = APIRouter(prefix="/products", tags=["products"])


class PublicProductShopResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    source_id: str
    name: str


class PublicProductLatestPriceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    price: Decimal | None
    currency: str
    unit_raw: str | None
    source_updated_at: datetime | None
    parsed_at: datetime


class PublicProductSearchItemResponse(BaseModel):
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
    shop: PublicProductShopResponse
    latest_price: PublicProductLatestPriceResponse | None


class PublicProductSearchResponse(BaseModel):
    items: list[PublicProductSearchItemResponse]
    limit: int
    offset: int
    total: int


class PublicProductPriceSnapshotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    price: Decimal | None
    currency: str
    unit_raw: str | None
    source_updated_at: datetime | None
    parsed_at: datetime


class PublicProductPriceHistoryResponse(BaseModel):
    product_id: int
    items: list[PublicProductPriceSnapshotResponse]


@router.get("", response_model=PublicProductSearchResponse)
def search_products(
    session: Annotated[Session, Depends(get_session)],
    q: str | None = None,
    category: int | None = None,
    category_id: int | None = None,
    category_slug: str | None = None,
    uncategorized: bool = False,
    shop: int | None = None,
    sort: ProductSort = "-last_seen_at",
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PublicProductSearchResponse:
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
    catalog = ProductCatalog(session, public_visibility=True)
    items = [
        PublicProductSearchItemResponse.model_validate(item)
        for item in catalog.search_products(filters)
    ]
    return PublicProductSearchResponse(
        items=items,
        limit=limit,
        offset=offset,
        total=catalog.count_products(filters),
    )


@router.get("/{product_id}", response_model=PublicProductSearchItemResponse)
def get_product(
    product_id: int,
    session: Annotated[Session, Depends(get_session)],
) -> PublicProductSearchItemResponse:
    item = ProductCatalog(session, public_visibility=True).get_product(product_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Source product not found")
    return PublicProductSearchItemResponse.model_validate(item)


@router.get("/{product_id}/prices", response_model=PublicProductPriceHistoryResponse)
def list_product_prices(
    product_id: int,
    session: Annotated[Session, Depends(get_session)],
) -> PublicProductPriceHistoryResponse:
    catalog = ProductCatalog(session, public_visibility=True)
    if not catalog.source_product_exists(product_id):
        raise HTTPException(status_code=404, detail="Source product not found")

    items = [
        PublicProductPriceSnapshotResponse.model_validate(item)
        for item in catalog.list_price_history(product_id)
    ]
    return PublicProductPriceHistoryResponse(product_id=product_id, items=items)
