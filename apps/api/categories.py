from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session
from stroyhub.catalog.categories import CategoryCatalog
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


@router.get("", response_model=CategoryTreeResponse)
def list_categories(
    session: Annotated[Session, Depends(get_session)],
) -> CategoryTreeResponse:
    items = [
        CategoryTreeItemResponse.model_validate(item)
        for item in CategoryCatalog(session).list_tree()
    ]
    return CategoryTreeResponse(items=items)
