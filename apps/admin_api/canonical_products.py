from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session
from stroyhub.catalog.canonical_products import (
    CanonicalProductCatalog,
    CanonicalProductFilters,
)
from stroyhub.db import get_session
from stroyhub.db.repositories import CanonicalProductCreate, CanonicalProductRepository
from stroyhub.models import Category, SourceProduct
from stroyhub.parsers.common import JsonObject, normalize_title

router = APIRouter(prefix="/canonical-products", tags=["canonical-products"])


class CanonicalCategoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    name: str


class CanonicalMatchCountsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    accepted: int
    candidate: int
    rejected: int


class CanonicalProductResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    normalized_title: str
    category_id: int | None
    category: CanonicalCategoryResponse | None
    brand: str | None
    model: str | None
    unit_raw: str | None
    attributes: dict[str, Any] | None
    match_status: str
    created_at: datetime
    updated_at: datetime
    match_counts: CanonicalMatchCountsResponse


class CanonicalLinkedSourceProductResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    match_id: int
    source: str
    source_product_id: str | None
    title: str
    normalized_title: str
    shop_id: int
    shop_name: str
    shop_source_id: str
    category_raw: str | None
    unit_raw: str | None
    source_url: str | None
    image_url: str | None
    last_seen_at: datetime
    latest_price: "CanonicalSourceLatestPriceResponse | None"
    confidence: Decimal


class CanonicalSourceLatestPriceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    price: Decimal | None
    currency: str
    unit_raw: str | None
    source_updated_at: datetime | None
    parsed_at: datetime


class CanonicalOfferGroupResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source: str
    shop_id: int
    shop_source_id: str
    shop_name: str
    items: list[CanonicalLinkedSourceProductResponse]


class CanonicalProductDetailResponse(CanonicalProductResponse):
    accepted_source_products: list[CanonicalLinkedSourceProductResponse]
    accepted_offer_groups: list[CanonicalOfferGroupResponse]
    candidate_source_products: list[CanonicalLinkedSourceProductResponse]
    rejected_source_products: list[CanonicalLinkedSourceProductResponse]


class CanonicalProductListResponse(BaseModel):
    items: list[CanonicalProductResponse]
    limit: int
    offset: int
    total: int


class CanonicalProductCreateRequest(BaseModel):
    title: str
    normalized_title: str | None = None
    category_id: int | None = None
    brand: str | None = None
    model: str | None = None
    unit_raw: str | None = None
    attributes: dict[str, Any] | None = None
    match_status: str = "active"


class CanonicalProductFromSourceRequest(BaseModel):
    title: str | None = None
    normalized_title: str | None = None
    category_id: int | None = None
    brand: str | None = None
    model: str | None = None
    unit_raw: str | None = None
    attributes: dict[str, Any] | None = None
    match_status: str = "active"


class CanonicalProductUpdateRequest(BaseModel):
    title: str | None = None
    normalized_title: str | None = None
    category_id: int | None = None
    brand: str | None = None
    model: str | None = None
    unit_raw: str | None = None
    attributes: dict[str, Any] | None = None
    match_status: str | None = None


@router.get("", response_model=CanonicalProductListResponse)
def list_canonical_products(
    session: Annotated[Session, Depends(get_session)],
    q: str | None = None,
    category_id: int | None = None,
    match_status: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CanonicalProductListResponse:
    page = CanonicalProductCatalog(session).list_products(
        CanonicalProductFilters(
            q=q,
            category_id=category_id,
            match_status=match_status,
            limit=limit,
            offset=offset,
        )
    )
    return CanonicalProductListResponse(
        items=[CanonicalProductResponse.model_validate(item) for item in page.items],
        limit=page.limit,
        offset=page.offset,
        total=page.total,
    )


@router.post("", response_model=CanonicalProductDetailResponse, status_code=201)
def create_canonical_product(
    payload: CanonicalProductCreateRequest,
    session: Annotated[Session, Depends(get_session)],
) -> CanonicalProductDetailResponse:
    _ensure_category_exists(session, payload.category_id)
    product = CanonicalProductRepository(session).create(
        CanonicalProductCreate(
            title=payload.title,
            normalized_title=payload.normalized_title or normalize_title(payload.title),
            category_id=payload.category_id,
            brand=payload.brand,
            model=payload.model,
            unit_raw=payload.unit_raw,
            attributes=_json_object(payload.attributes),
            match_status=payload.match_status,
        )
    )
    session.commit()
    return _canonical_detail_response(session, product.id)


@router.post(
    "/from-source/{source_product_id}",
    response_model=CanonicalProductDetailResponse,
    status_code=201,
)
def create_canonical_product_from_source(
    source_product_id: int,
    payload: CanonicalProductFromSourceRequest,
    session: Annotated[Session, Depends(get_session)],
) -> CanonicalProductDetailResponse:
    source_product = session.get(SourceProduct, source_product_id)
    if source_product is None:
        raise HTTPException(status_code=404, detail="Source product not found")

    category_id = (
        payload.category_id if payload.category_id is not None else source_product.category_id
    )
    _ensure_category_exists(session, category_id)
    title = payload.title or source_product.title
    product = CanonicalProductRepository(session).create(
        CanonicalProductCreate(
            title=title,
            normalized_title=payload.normalized_title or normalize_title(title),
            category_id=category_id,
            brand=payload.brand,
            model=payload.model,
            unit_raw=payload.unit_raw if payload.unit_raw is not None else source_product.unit_raw,
            attributes=_json_object(payload.attributes),
            match_status=payload.match_status,
        )
    )
    session.commit()
    return _canonical_detail_response(session, product.id)


@router.get("/{canonical_product_id}", response_model=CanonicalProductDetailResponse)
def get_canonical_product(
    canonical_product_id: int,
    session: Annotated[Session, Depends(get_session)],
) -> CanonicalProductDetailResponse:
    return _canonical_detail_response(session, canonical_product_id)


@router.patch("/{canonical_product_id}", response_model=CanonicalProductDetailResponse)
def update_canonical_product(
    canonical_product_id: int,
    payload: CanonicalProductUpdateRequest,
    session: Annotated[Session, Depends(get_session)],
) -> CanonicalProductDetailResponse:
    product = CanonicalProductRepository(session).get(canonical_product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Canonical product not found")

    if "category_id" in payload.model_fields_set:
        _ensure_category_exists(session, payload.category_id)
        product.category_id = payload.category_id
    if payload.title is not None:
        product.title = payload.title
        if "normalized_title" not in payload.model_fields_set:
            product.normalized_title = normalize_title(payload.title)
    if payload.normalized_title is not None:
        product.normalized_title = payload.normalized_title
    if "brand" in payload.model_fields_set:
        product.brand = payload.brand
    if "model" in payload.model_fields_set:
        product.model = payload.model
    if "unit_raw" in payload.model_fields_set:
        product.unit_raw = payload.unit_raw
    if "attributes" in payload.model_fields_set:
        product.attributes = _json_object(payload.attributes)
    if payload.match_status is not None:
        product.match_status = payload.match_status

    session.commit()
    return _canonical_detail_response(session, canonical_product_id)


def _canonical_detail_response(
    session: Session,
    canonical_product_id: int,
) -> CanonicalProductDetailResponse:
    detail = CanonicalProductCatalog(session).get_detail(canonical_product_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Canonical product not found")
    return CanonicalProductDetailResponse.model_validate(detail)


def _ensure_category_exists(session: Session, category_id: int | None) -> None:
    if category_id is not None and session.get(Category, category_id) is None:
        raise HTTPException(status_code=404, detail="Category not found")


def _json_object(value: dict[str, Any] | None) -> JsonObject | None:
    return value
