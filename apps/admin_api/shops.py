from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Response, status
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
from stroyhub.models import Shop
from stroyhub.scraping.enqueue import (
    clear_enqueue_failed,
    enqueue_failure_state,
    mark_enqueue_failed,
)
from stroyhub.scraping.twogis import build_twogis_large_catalog_raw, twogis_large_catalog_state

from apps.admin_api.errors import (
    ApiError,
    ValueErrorRule,
    api_error_responses,
    value_error_mapper,
)
from apps.admin_api.scrape_queue import enqueue_shop_scrape
from apps.admin_api.validation import ShopIdentityStatus, ShopScrapeStatus

router = APIRouter(prefix="/shops", tags=["shops"])
identity_router = APIRouter(prefix="/shop-identities", tags=["shop-identities"])


class ShopIdentitySummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    display_name: str
    status: str
    preferred_source: str | None


class TwogisLargeCatalogStateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    enabled: bool
    threshold: int
    total: int | None
    page_size: int
    pages_per_run: int
    next_page: int
    items_loaded: int
    completed: bool
    last_stop_reason: str | None = None


class EnqueueFailureResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    operation: str
    failed_at: str
    reason: str


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
    twogis_large_catalog: TwogisLargeCatalogStateResponse | None = None
    enqueue_failed: EnqueueFailureResponse | None = None


class ShopListResponse(BaseModel):
    items: list[ShopListItemResponse]


class ShopScrapeRetryResponse(BaseModel):
    shop_id: int
    source: str
    source_type: str
    status: str
    task_id: str | None = None
    reason: str | None = None

class AsyncOperationAcceptedResponse(BaseModel):
    operation: str
    status: str
    task_id: str
    shop_id: int


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
    status: ShopIdentityStatus = "active"
    notes: str | None = None
    locked_fields: dict[str, object] | None = None


class ShopIdentityUpdateRequest(BaseModel):
    display_name: str | None = None
    address: str | None = None
    website_url: str | None = None
    preferred_source: str | None = None
    status: ShopIdentityStatus | None = None
    notes: str | None = None
    locked_fields: dict[str, object] | None = None


@router.get("", response_model=ShopListResponse)
def list_shops(
    session: Annotated[Session, Depends(get_session)],
    source: str | None = None,
    status: ShopScrapeStatus | None = None,
    source_type: str | None = None,
    identity_id: Annotated[int | None, Query(gt=0)] = None,
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
    status: ShopIdentityStatus | None = None,
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
    identity_id: Annotated[int, Path(gt=0)],
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
    identity_id: Annotated[int, Path(gt=0)],
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
    shop_id: Annotated[int, Path(gt=0)],
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
    shop_id: Annotated[int, Path(gt=0)],
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


@router.post(
    "/{shop_id}/scrape/retry",
    response_model=ShopScrapeRetryResponse,
    responses=api_error_responses(400, 404, 409, 503),
)
def retry_shop_scrape(
    shop_id: Annotated[int, Path(gt=0)],
    session: Annotated[Session, Depends(get_session)],
) -> ShopScrapeRetryResponse:
    shop = session.get(Shop, shop_id)
    if shop is None:
        raise ApiError(status_code=404, code="shop_not_found", message="shop not found")
    if shop.scrape_status == "disabled":
        raise ApiError(
            status_code=400,
            code="shop_retry_disabled_source",
            message="disabled shop source cannot be retried",
        )
    if shop.scrape_status == "running":
        raise ApiError(
            status_code=409,
            code="shop_scrape_already_running",
            message="shop scrape is already running",
        )
    has_failed_enqueue = enqueue_failure_state(shop.raw) is not None
    if shop.scrape_status not in {"failed", "partial"} and not (
        shop.scrape_status == "scheduled" and has_failed_enqueue
    ):
        raise ApiError(
            status_code=400,
            code="shop_retry_status_not_allowed",
            message="only failed, partial, or enqueue-failed scheduled scrapes can be retried",
        )

    shop.scrape_status = "scheduled"
    shop.next_scrape_at = datetime.now(UTC)
    session.commit()

    result = enqueue_shop_scrape(shop.id)
    if str(result.get("status")) == "enqueue_failed":
        mark_enqueue_failed(
            shop,
            operation="shop_retry",
            reason=str(result.get("reason") or "enqueue failed"),
        )
        session.commit()
        raise ApiError(
            status_code=503,
            code="enqueue_failed",
            message=str(result.get("reason") or "enqueue failed"),
        )
    clear_enqueue_failed(shop)
    session.commit()
    task_id = result.get("task_id")
    reason = result.get("reason")
    return ShopScrapeRetryResponse(
        shop_id=shop.id,
        source=shop.source,
        source_type=shop.source_type,
        status=str(result.get("status", "queued")),
        task_id=task_id if isinstance(task_id, str) else None,
        reason=reason if isinstance(reason, str) else None,
    )


@router.post(
    "/{shop_id}/twogis-large-catalog/enable",
    response_model=AsyncOperationAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses=api_error_responses(400, 404, 503),
)
def enable_twogis_large_catalog(
    shop_id: Annotated[int, Path(gt=0)],
    session: Annotated[Session, Depends(get_session)],
) -> AsyncOperationAcceptedResponse:
    shop = _get_twogis_shop(shop_id, session)
    from apps.worker.tasks import enable_twogis_large_catalog_task

    try:
        task = enable_twogis_large_catalog_task.delay(shop.id)
    except Exception as exc:
        raise ApiError(status_code=503, code="enqueue_failed", message=str(exc)) from exc
    return AsyncOperationAcceptedResponse(
        operation="enable_twogis_large_catalog",
        status="queued",
        task_id=task.id,
        shop_id=shop.id,
    )


@router.post(
    "/{shop_id}/twogis-large-catalog/disable",
    response_model=ShopListItemResponse,
    responses=api_error_responses(400, 404),
)
def disable_twogis_large_catalog(
    shop_id: Annotated[int, Path(gt=0)],
    session: Annotated[Session, Depends(get_session)],
) -> ShopListItemResponse:
    shop = _get_twogis_shop(shop_id, session)
    state = twogis_large_catalog_state(shop.raw)
    raw = dict(shop.raw or {})
    raw["twogis_large_catalog"] = build_twogis_large_catalog_raw(
        enabled=False,
        total=state.total if state is not None else None,
        next_page=state.next_page if state is not None else 1,
        items_loaded=state.items_loaded if state is not None else 0,
        completed=state.completed if state is not None else False,
        last_stop_reason="operator_disabled",
    )
    shop.raw = raw
    shop.scrape_status = "disabled"
    session.commit()
    session.expire_all()
    return _shop_response(shop_id, session)


def _identity_response(identity_id: int, session: Session) -> ShopIdentityResponse:
    items = ShopCatalog(session).list_identities(ShopIdentityListFilters())
    for item in items:
        if item.id == identity_id:
            return ShopIdentityResponse.model_validate(item)
    raise ApiError(
        status_code=404,
        code="shop_identity_not_found",
        message="shop identity not found",
    )


def _shop_response(shop_id: int, session: Session) -> ShopListItemResponse:
    items = ShopCatalog(session).list_shops(ShopListFilters())
    for item in items:
        if item.id == shop_id:
            return ShopListItemResponse.model_validate(item)
    raise ApiError(status_code=404, code="shop_not_found", message="shop not found")


def _get_twogis_shop(shop_id: int, session: Session) -> Shop:
    shop = session.get(Shop, shop_id)
    if shop is None:
        raise ApiError(status_code=404, code="shop_not_found", message="shop not found")
    if shop.source != "2gis":
        raise ApiError(
            status_code=400,
            code="large_catalog_requires_twogis",
            message="large catalog mode is only for 2GIS shops",
        )
    return shop


_http_error = value_error_mapper(
    (
        ValueErrorRule("shop identity not found", 404, "shop_identity_not_found"),
        ValueErrorRule("shop not found", 404, "shop_not_found"),
        ValueErrorRule("display_name must not be empty", 400, "display_name_empty"),
        ValueErrorRule("manual is not an accepted shop source", 400, "invalid_shop_source"),
    )
)
