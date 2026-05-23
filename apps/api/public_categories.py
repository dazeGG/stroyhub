from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session
from stroyhub.catalog.categories import CategoryCatalog, CategoryPriceSummaryFilters
from stroyhub.db import get_session

router = APIRouter(prefix="/categories", tags=["categories"])


class PublicCategoryTreeItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    name: str
    parent_id: int | None
    product_count: int
    children: list["PublicCategoryTreeItemResponse"]


class PublicCategoryTreeResponse(BaseModel):
    items: list[PublicCategoryTreeItemResponse]


class PublicCategoryPriceSummaryItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    category_id: int | None
    category_slug: str | None
    category_name: str | None
    product_count: int
    priced_product_count: int
    min_price: Decimal | None
    avg_price: Decimal | None
    max_price: Decimal | None


class PublicCategoryPriceSummaryResponse(BaseModel):
    items: list[PublicCategoryPriceSummaryItemResponse]


@router.get("", response_model=PublicCategoryTreeResponse)
def list_categories(
    session: Annotated[Session, Depends(get_session)],
) -> PublicCategoryTreeResponse:
    items = [
        PublicCategoryTreeItemResponse.model_validate(item)
        for item in CategoryCatalog(session).list_tree()
    ]
    return PublicCategoryTreeResponse(items=items)


@router.get("/price-summary", response_model=PublicCategoryPriceSummaryResponse)
def list_category_price_summary(
    session: Annotated[Session, Depends(get_session)],
    source: str | None = None,
    shop: int | None = None,
) -> PublicCategoryPriceSummaryResponse:
    filters = CategoryPriceSummaryFilters(source=source, shop_id=shop)
    items = [
        PublicCategoryPriceSummaryItemResponse.model_validate(item)
        for item in CategoryCatalog(session).list_price_summary(filters)
    ]
    return PublicCategoryPriceSummaryResponse(items=items)
