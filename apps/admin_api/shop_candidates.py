from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session
from stroyhub.catalog.official_sources import materialize_official_source
from stroyhub.catalog.shop_candidates import (
    CandidateListFilters,
    CandidateRefreshSummary,
    CandidateVerificationSummary,
    ShopCandidateCatalog,
)
from stroyhub.db import get_session
from stroyhub.models import Shop, ShopIdentity, ShopSourceCandidate
from stroyhub.parsers.metalltorg import METALLTORG_SHOP_SOURCE_ID, METALLTORG_SOURCE
from stroyhub.parsers.unicom import UNICOM_DEFAULT_SHOP_SOURCE_ID, UNICOM_SOURCE
from stroyhub.scraping.enqueue import clear_enqueue_failed, mark_enqueue_failed

from apps.admin_api.scrape_queue import enqueue_shop_scrape

router = APIRouter(prefix="/shop-source-candidates", tags=["shop-source-candidates"])


class ShopSourceCandidateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    source_id: str
    source_type: str
    display_name: str
    address: str | None
    website_url: str | None
    rubrics: str | None
    status: str
    has_products: bool
    has_prices: bool
    has_website: bool
    product_count: int
    priced_product_count: int
    priority: int
    priority_reason: str
    last_seen_at: datetime | None
    last_checked_at: datetime | None
    missing_since: datetime | None
    approved_shop_id: int | None
    official_strategy: dict[str, object] | None = None
    official_source_shop_id: int | None = None
    official_source_status: str | None = None
    official_source_last_scraped_at: datetime | None = None
    suggested_identity: dict[str, object] | None = None
    scrape_result: dict[str, object] | None = None


class ShopSourceCandidateApproveRequest(BaseModel):
    shop_identity_id: int | None = None


class OfficialStrategyMaterializeRequest(BaseModel):
    run_scrape: bool = True


class ShopSourceCandidateGroupResponse(BaseModel):
    key: str
    label: str
    official_strategy: dict[str, object] | None = None
    candidate_ids: list[int]
    size: int
    pending_count: int
    has_prices: bool
    has_website: bool
    priority: int
    items: list[ShopSourceCandidateResponse]


class ShopSourceCandidateListResponse(BaseModel):
    items: list[ShopSourceCandidateResponse]
    groups: list[ShopSourceCandidateGroupResponse] = []


class ShopSourceCandidateRefreshResponse(BaseModel):
    checked: int
    created: int
    updated: int
    stale: int
    skipped_approved: int
    items: list[ShopSourceCandidateResponse]
    groups: list[ShopSourceCandidateGroupResponse] = []


class ShopSourceCandidateVerificationResponse(BaseModel):
    candidate: ShopSourceCandidateResponse
    website_found: bool
    products_found: bool
    website_url: str | None
    product_count: int
    priced_product_count: int


class OfficialSourceShopResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    shop_identity_id: int | None
    source: str
    source_id: str
    source_type: str
    name: str
    scrape_status: str
    last_scraped_at: datetime | None


class OfficialSourceIdentityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    display_name: str
    preferred_source: str | None
    status: str


class OfficialStrategyMaterializeResponse(BaseModel):
    source: str
    shop: OfficialSourceShopResponse
    identity: OfficialSourceIdentityResponse
    related_candidate_ids: list[int]
    scrape_result: dict[str, object] | None = None


@router.get("", response_model=ShopSourceCandidateListResponse)
def list_shop_source_candidates(
    session: Annotated[Session, Depends(get_session)],
    status: str | None = None,
    include_approved: bool = False,
) -> ShopSourceCandidateListResponse:
    catalog = ShopCandidateCatalog(session)
    try:
        items = catalog.list_candidates(
            CandidateListFilters(status=status, include_approved=include_approved)
        )
    except ValueError as exc:
        raise _http_error(exc) from exc

    response_items = [_candidate_response_model(item, catalog, session=session) for item in items]
    return ShopSourceCandidateListResponse(
        items=response_items,
        groups=_candidate_groups(response_items),
    )


@router.post("/refresh", response_model=ShopSourceCandidateRefreshResponse)
def refresh_shop_source_candidates(
    session: Annotated[Session, Depends(get_session)],
) -> ShopSourceCandidateRefreshResponse:
    catalog = ShopCandidateCatalog(session)
    summary = catalog.refresh_from_twogis()
    session.commit()
    session.expire_all()
    items = catalog.list_candidates(CandidateListFilters())
    return _refresh_response(summary, items, catalog, session=session)


@router.post("/{candidate_id}/approve", response_model=ShopSourceCandidateResponse)
def approve_shop_source_candidate(
    candidate_id: int,
    session: Annotated[Session, Depends(get_session)],
    payload: ShopSourceCandidateApproveRequest | None = None,
) -> ShopSourceCandidateResponse:
    catalog = ShopCandidateCatalog(session)
    try:
        candidate = catalog.approve(
            candidate_id,
            shop_identity_id=payload.shop_identity_id if payload is not None else None,
        )
    except ValueError as exc:
        raise _http_error(exc) from exc

    approved_candidate_id = candidate.id
    approved_shop_id = candidate.approved_shop_id
    session.commit()
    scrape_result: dict[str, object] | None = None
    if approved_shop_id is not None:
        scrape_result = enqueue_shop_scrape(approved_shop_id)
        shop = session.get(Shop, approved_shop_id)
        if str(scrape_result.get("status")) == "enqueue_failed":
            if shop is not None:
                mark_enqueue_failed(
                    shop,
                    operation="candidate_approve",
                    reason=str(scrape_result.get("reason") or "enqueue failed"),
                )
                session.commit()
            raise HTTPException(
                status_code=503,
                detail=str(scrape_result.get("reason") or "enqueue failed"),
            )
        if shop is not None:
            clear_enqueue_failed(shop)
            session.commit()
    session.expire_all()
    return _candidate_response(approved_candidate_id, session, scrape_result=scrape_result)


@router.post(
    "/{candidate_id}/verify-twogis-data",
    response_model=ShopSourceCandidateVerificationResponse,
)
def verify_shop_source_candidate_twogis_data(
    candidate_id: int,
    session: Annotated[Session, Depends(get_session)],
) -> ShopSourceCandidateVerificationResponse:
    catalog = ShopCandidateCatalog(session)
    try:
        candidate, verification = catalog.verify_twogis_data(candidate_id)
    except ValueError as exc:
        raise _http_error(exc) from exc

    candidate_id = candidate.id
    session.commit()
    session.expire_all()
    return _verification_response(candidate_id, verification, session)


@router.post(
    "/official-strategies/{source}/materialize",
    response_model=OfficialStrategyMaterializeResponse,
)
def materialize_official_strategy(
    source: str,
    session: Annotated[Session, Depends(get_session)],
    payload: OfficialStrategyMaterializeRequest | None = None,
) -> OfficialStrategyMaterializeResponse:
    try:
        materialized = materialize_official_source(session, source)
    except ValueError as exc:
        raise _http_error(exc) from exc

    shop_id = materialized.shop.id
    session.commit()
    scrape_result: dict[str, object] | None = None
    if payload is None or payload.run_scrape:
        scrape_result = enqueue_shop_scrape(shop_id)
        shop = session.get(Shop, shop_id)
        if str(scrape_result.get("status")) == "enqueue_failed":
            if shop is not None:
                mark_enqueue_failed(
                    shop,
                    operation="official_materialize",
                    reason=str(scrape_result.get("reason") or "enqueue failed"),
                )
                session.commit()
            raise HTTPException(
                status_code=503,
                detail=str(scrape_result.get("reason") or "enqueue failed"),
            )
        if shop is not None:
            clear_enqueue_failed(shop)
            session.commit()

    session.expire_all()
    shop = session.get(Shop, shop_id)
    identity = session.get(ShopIdentity, materialized.identity.id)
    if shop is None or identity is None:
        raise HTTPException(status_code=404, detail="official source was not found")
    return OfficialStrategyMaterializeResponse(
        source=source,
        shop=OfficialSourceShopResponse.model_validate(shop),
        identity=OfficialSourceIdentityResponse.model_validate(identity),
        related_candidate_ids=materialized.related_candidate_ids,
        scrape_result=scrape_result,
    )


def _refresh_response(
    summary: CandidateRefreshSummary,
    items: list[ShopSourceCandidate],
    catalog: ShopCandidateCatalog,
    session: Session,
) -> ShopSourceCandidateRefreshResponse:
    response_items = [
        _candidate_response_model(item, catalog, session=session) for item in items
    ]
    return ShopSourceCandidateRefreshResponse(
        checked=summary.checked,
        created=summary.created,
        updated=summary.updated,
        stale=summary.stale,
        skipped_approved=summary.skipped_approved,
        items=response_items,
        groups=_candidate_groups(response_items),
    )


def _candidate_response(
    candidate_id: int,
    session: Session,
    scrape_result: dict[str, object] | None = None,
) -> ShopSourceCandidateResponse:
    catalog = ShopCandidateCatalog(session)
    for item in catalog.list_candidates(
        CandidateListFilters(include_approved=True)
    ):
        if item.id == candidate_id:
            return _candidate_response_model(
                item,
                catalog,
                scrape_result=scrape_result,
                session=session,
            )
    raise HTTPException(status_code=404, detail="shop source candidate not found")


def _verification_response(
    candidate_id: int,
    verification: CandidateVerificationSummary,
    session: Session,
) -> ShopSourceCandidateVerificationResponse:
    candidate = _candidate_response(candidate_id, session)
    return ShopSourceCandidateVerificationResponse(
        candidate=candidate,
        website_found=verification.website_found,
        products_found=verification.products_found,
        website_url=verification.website_url,
        product_count=verification.product_count,
        priced_product_count=verification.priced_product_count,
    )


def _candidate_response_model(
    candidate: ShopSourceCandidate,
    catalog: ShopCandidateCatalog,
    scrape_result: dict[str, object] | None = None,
    session: Session | None = None,
) -> ShopSourceCandidateResponse:
    response = ShopSourceCandidateResponse.model_validate(candidate)
    response.scrape_result = scrape_result
    if isinstance(candidate.raw, dict):
        strategy = candidate.raw.get("official_strategy")
        if isinstance(strategy, dict):
            response.official_strategy = strategy
            if session is not None:
                official_shop = _official_shop_for_strategy(session, strategy)
                if official_shop is not None:
                    response.official_source_shop_id = official_shop.id
                    response.official_source_status = official_shop.scrape_status
                    response.official_source_last_scraped_at = official_shop.last_scraped_at
    suggestion = catalog.suggest_identity(candidate)
    if suggestion is not None:
        response.suggested_identity = {
            "id": suggestion.id,
            "display_name": suggestion.display_name,
            "status": suggestion.status,
            "source_count": suggestion.source_count,
            "reason": suggestion.reason,
        }
    return response


def _candidate_groups(
    items: list[ShopSourceCandidateResponse],
) -> list[ShopSourceCandidateGroupResponse]:
    grouped: dict[str, list[ShopSourceCandidateResponse]] = {}
    for item in items:
        grouped.setdefault(_group_key(item), []).append(item)

    groups = [
        _candidate_group(key, group_items)
        for key, group_items in grouped.items()
        if len(group_items) > 1 or group_items[0].official_strategy is not None
    ]
    groups.sort(key=lambda group: (-group.priority, group.label.casefold(), group.key))
    return groups


def _candidate_group(
    key: str,
    items: list[ShopSourceCandidateResponse],
) -> ShopSourceCandidateGroupResponse:
    first = items[0]
    official_strategy = first.official_strategy
    label = (
        str(official_strategy.get("label"))
        if official_strategy is not None and official_strategy.get("label")
        else first.display_name
    )
    return ShopSourceCandidateGroupResponse(
        key=key,
        label=label,
        official_strategy=official_strategy,
        candidate_ids=[item.id for item in items],
        size=len(items),
        pending_count=sum(1 for item in items if item.status == "pending"),
        has_prices=any(item.has_prices for item in items),
        has_website=any(item.has_website for item in items),
        priority=max(item.priority for item in items),
        items=items,
    )


def _group_key(item: ShopSourceCandidateResponse) -> str:
    if item.official_strategy is not None:
        source = item.official_strategy.get("source")
        if isinstance(source, str) and source:
            return f"official:{source}"
    return f"name:{_normalize_candidate_name(item.display_name)}"


def _normalize_candidate_name(value: str) -> str:
    import re

    normalized = value.casefold().replace("ё", "е")
    return re.sub(r"[^0-9a-zа-я]+", "", normalized)


def _official_shop_for_strategy(session: Session, strategy: dict[str, object]) -> Shop | None:
    source = strategy.get("source")
    if source == UNICOM_SOURCE:
        return session.scalar(
            select(Shop).where(
                Shop.source == UNICOM_SOURCE,
                Shop.source_id == UNICOM_DEFAULT_SHOP_SOURCE_ID,
            )
        )
    if source == METALLTORG_SOURCE:
        return session.scalar(
            select(Shop).where(
                Shop.source == METALLTORG_SOURCE,
                Shop.source_id == METALLTORG_SHOP_SOURCE_ID,
            )
        )
    return None


def _http_error(error: ValueError) -> HTTPException:
    detail = str(error)
    if "not found" in detail:
        return HTTPException(status_code=404, detail=detail)
    return HTTPException(status_code=400, detail=detail)
