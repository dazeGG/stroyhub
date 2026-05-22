from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session
from stroyhub.catalog.shops import (
    ShopCatalog,
    ShopIdentityListFilters,
    ShopListFilters,
)
from stroyhub.db import get_session
from stroyhub.db.repositories import (
    ShopIdentityCreate,
    ShopIdentityRepository,
    ShopIdentityUpdate,
)

router = APIRouter(prefix="/shops", tags=["shops"])
identity_router = APIRouter(prefix="/shop-identities", tags=["shop-identities"])


class ShopIdentitySummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    display_name: str
    status: str
    preferred_source: str | None


class ShopListItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    shop_identity_id: int | None
    identity: ShopIdentitySummaryResponse | None
    source: str
    source_id: str
    source_type: str
    name: str
    address: str | None
    url: str | None
    scrape_status: str
    last_scraped_at: datetime | None
    next_scrape_at: datetime | None
    scrape_interval: int
    error_count: int
    is_preferred_source: bool


class ShopListResponse(BaseModel):
    items: list[ShopListItemResponse]


class ShopIdentityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    display_name: str
    address: str | None
    website_url: str | None
    preferred_source: str | None
    status: str
    notes: str | None
    locked_fields: dict[str, object] | None
    source_count: int | None = None


class ShopIdentityListResponse(BaseModel):
    items: list[ShopIdentityResponse]


class ShopIdentityCreateRequest(BaseModel):
    display_name: str
    address: str | None = None
    website_url: str | None = None
    preferred_source: str | None = None
    status: str = "active"
    notes: str | None = None
    locked_fields: dict[str, object] | None = None


class ShopIdentityUpdateRequest(BaseModel):
    display_name: str | None = None
    address: str | None = None
    website_url: str | None = None
    preferred_source: str | None = None
    status: str | None = None
    notes: str | None = None
    locked_fields: dict[str, object] | None = None


@router.get("", response_model=ShopListResponse)
def list_shops(
    session: Annotated[Session, Depends(get_session)],
    source: str | None = None,
    status: str | None = None,
    source_type: str | None = None,
    identity_id: int | None = None,
    identity: str | None = None,
) -> ShopListResponse:
    filters = ShopListFilters(
        source=source,
        status=status,
        source_type=source_type,
        identity_id=identity_id,
        identity=identity,
    )
    items = [
        ShopListItemResponse.model_validate(item)
        for item in ShopCatalog(session).list_shops(filters)
    ]
    return ShopListResponse(items=items)


@identity_router.get("", response_model=ShopIdentityListResponse)
def list_shop_identities(
    session: Annotated[Session, Depends(get_session)],
    status: str | None = None,
) -> ShopIdentityListResponse:
    filters = ShopIdentityListFilters(status=status)
    items = [
        ShopIdentityResponse.model_validate(item)
        for item in ShopCatalog(session).list_identities(filters)
    ]
    return ShopIdentityListResponse(items=items)


@identity_router.post("", response_model=ShopIdentityResponse, status_code=201)
def create_shop_identity(
    payload: ShopIdentityCreateRequest,
    session: Annotated[Session, Depends(get_session)],
) -> ShopIdentityResponse:
    repository = ShopIdentityRepository(session)
    try:
        identity = repository.create(
            ShopIdentityCreate(
                display_name=payload.display_name,
                address=payload.address,
                website_url=payload.website_url,
                preferred_source=payload.preferred_source,
                status=payload.status,
                notes=payload.notes,
                locked_fields=payload.locked_fields,
            )
        )
    except ValueError as exc:
        raise _http_error(exc) from exc

    session.commit()
    session.expire_all()
    return _identity_response(identity.id, session)


@identity_router.patch("/{identity_id}", response_model=ShopIdentityResponse)
def update_shop_identity(
    identity_id: int,
    payload: ShopIdentityUpdateRequest,
    session: Annotated[Session, Depends(get_session)],
) -> ShopIdentityResponse:
    repository = ShopIdentityRepository(session)
    try:
        identity = repository.update(
            identity_id,
            ShopIdentityUpdate(
                display_name=payload.display_name,
                address=payload.address,
                website_url=payload.website_url,
                preferred_source=payload.preferred_source,
                status=payload.status,
                notes=payload.notes,
                locked_fields=payload.locked_fields,
            ),
        )
    except ValueError as exc:
        raise _http_error(exc) from exc

    session.commit()
    session.expire_all()
    return _identity_response(identity.id, session)


@identity_router.delete("/{identity_id}", status_code=204)
def delete_shop_identity(
    identity_id: int,
    session: Annotated[Session, Depends(get_session)],
) -> Response:
    repository = ShopIdentityRepository(session)
    try:
        repository.delete(identity_id)
    except ValueError as exc:
        raise _http_error(exc) from exc

    session.commit()
    return Response(status_code=204)


@identity_router.post(
    "/{identity_id}/sources/{shop_id}",
    response_model=ShopListItemResponse,
)
def link_shop_source(
    identity_id: int,
    shop_id: int,
    session: Annotated[Session, Depends(get_session)],
) -> ShopListItemResponse:
    repository = ShopIdentityRepository(session)
    try:
        shop = repository.link_shop(identity_id=identity_id, shop_id=shop_id)
    except ValueError as exc:
        raise _http_error(exc) from exc

    session.commit()
    session.expire_all()
    return _shop_response(shop.id, session)


@router.delete("/{shop_id}/identity", response_model=ShopListItemResponse)
def unlink_shop_source(
    shop_id: int,
    session: Annotated[Session, Depends(get_session)],
) -> ShopListItemResponse:
    repository = ShopIdentityRepository(session)
    try:
        shop = repository.unlink_shop(shop_id=shop_id)
    except ValueError as exc:
        raise _http_error(exc) from exc

    session.commit()
    session.expire_all()
    return _shop_response(shop.id, session)


def _identity_response(identity_id: int, session: Session) -> ShopIdentityResponse:
    items = ShopCatalog(session).list_identities(ShopIdentityListFilters())
    for item in items:
        if item.id == identity_id:
            return ShopIdentityResponse.model_validate(item)
    raise HTTPException(status_code=404, detail="shop identity not found")


def _shop_response(shop_id: int, session: Session) -> ShopListItemResponse:
    items = ShopCatalog(session).list_shops(ShopListFilters())
    for item in items:
        if item.id == shop_id:
            return ShopListItemResponse.model_validate(item)
    raise HTTPException(status_code=404, detail="shop not found")


def _http_error(error: ValueError) -> HTTPException:
    detail = str(error)
    if "not found" in detail:
        return HTTPException(status_code=404, detail=detail)
    return HTTPException(status_code=400, detail=detail)
