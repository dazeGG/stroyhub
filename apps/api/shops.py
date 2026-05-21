from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session
from stroyhub.catalog.shops import ShopCatalog, ShopListFilters
from stroyhub.db import get_session

router = APIRouter(prefix="/shops", tags=["shops"])


class ShopListItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    source_id: str
    name: str
    address: str | None
    scrape_status: str
    last_scraped_at: datetime | None


class ShopListResponse(BaseModel):
    items: list[ShopListItemResponse]


@router.get("", response_model=ShopListResponse)
def list_shops(
    session: Annotated[Session, Depends(get_session)],
    source: str | None = None,
    status: str | None = None,
) -> ShopListResponse:
    filters = ShopListFilters(source=source, status=status)
    items = [
        ShopListItemResponse.model_validate(item)
        for item in ShopCatalog(session).list_shops(filters)
    ]
    return ShopListResponse(items=items)
