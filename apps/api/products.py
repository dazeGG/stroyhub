from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session
from stroyhub.catalog.products import ProductCatalog, ProductSearchFilters
from stroyhub.db import get_session

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


class ProductSearchResponse(BaseModel):
    items: list[ProductSearchItemResponse]
    limit: int
    offset: int


@router.get("", response_model=ProductSearchResponse)
def search_products(
    session: Annotated[Session, Depends(get_session)],
    q: str | None = None,
    category: int | None = None,
    shop: int | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ProductSearchResponse:
    filters = ProductSearchFilters(
        q=q,
        category_id=category,
        shop_id=shop,
        limit=limit,
        offset=offset,
    )
    items = [
        ProductSearchItemResponse.model_validate(item)
        for item in ProductCatalog(session).search_products(filters)
    ]
    return ProductSearchResponse(items=items, limit=limit, offset=offset)
