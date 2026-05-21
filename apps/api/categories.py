from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session
from stroyhub.catalog.categories import CategoryCatalog, CategoryPriceSummaryFilters
from stroyhub.db import get_session

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
