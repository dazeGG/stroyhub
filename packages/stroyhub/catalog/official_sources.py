from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from stroyhub.db.repositories import (
    ShopIdentityCreate,
    ShopIdentityRepository,
    ShopRepository,
    ShopUpsert,
)
from stroyhub.models import Shop, ShopIdentity, ShopSourceCandidate
from stroyhub.parsers.metalltorg import METALLTORG_SHOP_SOURCE_ID, METALLTORG_SOURCE
from stroyhub.parsers.unicom import UNICOM_DEFAULT_SHOP_SOURCE_ID, UNICOM_SOURCE
from stroyhub.scraping.metalltorg import (
    METALLTORG_DEFAULT_CATEGORY_URLS,
    METALLTORG_DEFAULT_MAX_PAGES,
    METALLTORG_DEFAULT_SHOP_NAME,
    METALLTORG_DEFAULT_SHOP_URL,
    METALLTORG_DEFAULT_TIMEOUT,
)
from stroyhub.scraping.unicom import (
    UNICOM_DEFAULT_CATEGORY_UUIDS,
    UNICOM_DEFAULT_LIMIT,
    UNICOM_DEFAULT_MAX_PAGES,
    UNICOM_DEFAULT_SHOP_NAME,
    UNICOM_DEFAULT_SHOP_URL,
    UNICOM_DEFAULT_SORT,
)


@dataclass(frozen=True, kw_only=True)
class OfficialSourceMaterialization:
    source: str
    identity: ShopIdentity
    shop: Shop
    related_candidate_ids: list[int]


def materialize_official_source(
    session: Session,
    source: str,
    *,
    scrape_interval: int = 86400,
) -> OfficialSourceMaterialization:
    if source == UNICOM_SOURCE:
        return _materialize_unicom(session, scrape_interval=scrape_interval)
    if source == METALLTORG_SOURCE:
        return _materialize_metalltorg(session, scrape_interval=scrape_interval)
    raise ValueError(f"unknown official source strategy: {source}")


def _materialize_unicom(
    session: Session,
    *,
    scrape_interval: int,
) -> OfficialSourceMaterialization:
    identity = _get_or_create_identity(
        session,
        display_name=UNICOM_DEFAULT_SHOP_NAME,
        website_url=UNICOM_DEFAULT_SHOP_URL,
        preferred_source=UNICOM_SOURCE,
    )
    repository = ShopRepository(session)
    existing = repository.get_by_source_id(
        source=UNICOM_SOURCE,
        source_id=UNICOM_DEFAULT_SHOP_SOURCE_ID,
    )
    raw = dict(existing.raw or {}) if existing is not None else {}
    raw.update(
        {
            "source": UNICOM_SOURCE,
            "source_type": "official_api",
            "category_uuids": list(UNICOM_DEFAULT_CATEGORY_UUIDS),
            "limit": UNICOM_DEFAULT_LIMIT,
            "max_pages": UNICOM_DEFAULT_MAX_PAGES,
            "sort": UNICOM_DEFAULT_SORT,
            "pacing": "sequential categories; no concurrent requests",
        }
    )
    shop = repository.upsert(
        ShopUpsert(
            source=UNICOM_SOURCE,
            source_id=UNICOM_DEFAULT_SHOP_SOURCE_ID,
            source_type="official_api",
            shop_identity_id=identity.id,
            name=UNICOM_DEFAULT_SHOP_NAME,
            url=UNICOM_DEFAULT_SHOP_URL,
            last_scraped_at=existing.last_scraped_at if existing is not None else None,
            next_scrape_at=_next_scrape_at(existing),
            scrape_interval=scrape_interval,
            scrape_status=existing.scrape_status if existing is not None else "scheduled",
            error_count=existing.error_count if existing is not None else None,
            raw=raw,
        )
    )
    return OfficialSourceMaterialization(
        source=UNICOM_SOURCE,
        identity=identity,
        shop=shop,
        related_candidate_ids=_related_candidate_ids(session, UNICOM_SOURCE),
    )


def _materialize_metalltorg(
    session: Session,
    *,
    scrape_interval: int,
) -> OfficialSourceMaterialization:
    identity = _get_or_create_identity(
        session,
        display_name=METALLTORG_DEFAULT_SHOP_NAME,
        website_url=METALLTORG_DEFAULT_SHOP_URL,
        preferred_source=METALLTORG_SOURCE,
    )
    repository = ShopRepository(session)
    existing = repository.get_by_source_id(
        source=METALLTORG_SOURCE,
        source_id=METALLTORG_SHOP_SOURCE_ID,
    )
    raw = dict(existing.raw or {}) if existing is not None else {}
    raw.update(
        {
            "source": METALLTORG_SOURCE,
            "source_type": "official_html",
            "category_urls": list(METALLTORG_DEFAULT_CATEGORY_URLS),
            "max_pages": METALLTORG_DEFAULT_MAX_PAGES,
            "timeout": METALLTORG_DEFAULT_TIMEOUT,
            "pacing": "sequential pages and categories; no concurrent requests",
            "selector_health": "brittle_html",
        }
    )
    shop = repository.upsert(
        ShopUpsert(
            source=METALLTORG_SOURCE,
            source_id=METALLTORG_SHOP_SOURCE_ID,
            source_type="official_html",
            shop_identity_id=identity.id,
            name=METALLTORG_DEFAULT_SHOP_NAME,
            url=METALLTORG_DEFAULT_SHOP_URL,
            last_scraped_at=existing.last_scraped_at if existing is not None else None,
            next_scrape_at=_next_scrape_at(existing),
            scrape_interval=scrape_interval,
            scrape_status=existing.scrape_status if existing is not None else "scheduled",
            error_count=existing.error_count if existing is not None else None,
            raw=raw,
        )
    )
    return OfficialSourceMaterialization(
        source=METALLTORG_SOURCE,
        identity=identity,
        shop=shop,
        related_candidate_ids=_related_candidate_ids(session, METALLTORG_SOURCE),
    )


def _get_or_create_identity(
    session: Session,
    *,
    display_name: str,
    website_url: str,
    preferred_source: str,
) -> ShopIdentity:
    identity = session.scalar(
        select(ShopIdentity)
        .where(ShopIdentity.display_name == display_name)
        .order_by(ShopIdentity.id.asc())
        .limit(1)
    )
    if identity is None:
        identity = session.scalar(
            select(ShopIdentity)
            .where(ShopIdentity.preferred_source == preferred_source)
            .order_by(ShopIdentity.id.asc())
            .limit(1)
        )
    if identity is not None:
        identity.preferred_source = preferred_source
        identity.website_url = identity.website_url or website_url
        locked_fields = dict(identity.locked_fields or {})
        locked_fields.update({"display_name": True, "website_url": True})
        identity.locked_fields = locked_fields
        session.flush()
        return identity

    return ShopIdentityRepository(session).create(
        ShopIdentityCreate(
            display_name=display_name,
            website_url=website_url,
            preferred_source=preferred_source,
            locked_fields={"display_name": True, "website_url": True},
        )
    )


def _next_scrape_at(existing: Shop | None) -> datetime:
    if existing is not None and existing.next_scrape_at is not None:
        return existing.next_scrape_at
    return datetime.now(UTC)


def _related_candidate_ids(session: Session, source: str) -> list[int]:
    candidates = session.scalars(
        select(ShopSourceCandidate).order_by(ShopSourceCandidate.id.asc())
    )
    related: list[int] = []
    for candidate in candidates:
        raw = candidate.raw
        if not isinstance(raw, dict):
            continue
        strategy = raw.get("official_strategy")
        if isinstance(strategy, dict) and strategy.get("source") == source:
            related.append(candidate.id)
    return related
