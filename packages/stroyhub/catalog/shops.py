from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from stroyhub.models.tables import Shop, ShopIdentity
from stroyhub.scraping.twogis import TwogisLargeCatalogState, twogis_large_catalog_state


@dataclass(frozen=True, kw_only=True)
class ShopListFilters:
    source: str | None = None
    status: str | None = None
    source_type: str | None = None
    identity_id: int | None = None
    identity: str | None = None


@dataclass(frozen=True, kw_only=True)
class ShopIdentitySummary:
    id: int
    display_name: str
    status: str
    preferred_source: str | None


@dataclass(frozen=True, kw_only=True)
class ShopListItem:
    id: int
    shop_identity_id: int | None
    identity: ShopIdentitySummary | None
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
    twogis_large_catalog: TwogisLargeCatalogState | None


@dataclass(frozen=True, kw_only=True)
class ShopIdentityListFilters:
    status: str | None = None


@dataclass(frozen=True, kw_only=True)
class ShopIdentityListItem:
    id: int
    display_name: str
    address: str | None
    website_url: str | None
    preferred_source: str | None
    status: str
    notes: str | None
    locked_fields: dict[str, object] | None
    source_count: int


class ShopCatalog:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_shops(self, filters: ShopListFilters) -> list[ShopListItem]:
        statement = select(Shop).order_by(Shop.name.asc(), Shop.id.asc())

        if filters.source is not None:
            source = filters.source.strip()
            if source:
                statement = statement.where(Shop.source == source)

        if filters.status is not None:
            status = filters.status.strip()
            if status:
                statement = statement.where(Shop.scrape_status == status)

        if filters.source_type is not None:
            source_type = filters.source_type.strip()
            if source_type:
                statement = statement.where(Shop.source_type == source_type)

        if filters.identity_id is not None:
            statement = statement.where(Shop.shop_identity_id == filters.identity_id)

        if filters.identity is not None:
            identity = filters.identity.strip()
            if identity == "linked":
                statement = statement.where(Shop.shop_identity_id.is_not(None))
            elif identity == "unlinked":
                statement = statement.where(Shop.shop_identity_id.is_(None))

        return [
            ShopListItem(
                id=shop.id,
                shop_identity_id=shop.shop_identity_id,
                identity=_shop_identity_summary(shop.shop_identity),
                source=shop.source,
                source_id=shop.source_id,
                source_type=shop.source_type,
                name=shop.name,
                address=shop.address,
                url=shop.url,
                scrape_status=shop.scrape_status,
                last_scraped_at=shop.last_scraped_at,
                next_scrape_at=shop.next_scrape_at,
                scrape_interval=shop.scrape_interval,
                error_count=shop.error_count,
                is_preferred_source=_is_preferred_source(shop),
                twogis_large_catalog=twogis_large_catalog_state(shop.raw),
            )
            for shop in self._session.scalars(statement)
        ]

    def list_identities(self, filters: ShopIdentityListFilters) -> list[ShopIdentityListItem]:
        statement = select(ShopIdentity).order_by(
            ShopIdentity.display_name.asc(),
            ShopIdentity.id.asc(),
        )

        if filters.status is not None:
            status = filters.status.strip()
            if status:
                statement = statement.where(ShopIdentity.status == status)

        return [
            ShopIdentityListItem(
                id=identity.id,
                display_name=identity.display_name,
                address=identity.address,
                website_url=identity.website_url,
                preferred_source=identity.preferred_source,
                status=identity.status,
                notes=identity.notes,
                locked_fields=identity.locked_fields,
                source_count=len(identity.source_shops),
            )
            for identity in self._session.scalars(statement)
        ]


def _shop_identity_summary(identity: ShopIdentity | None) -> ShopIdentitySummary | None:
    if identity is None:
        return None

    return ShopIdentitySummary(
        id=identity.id,
        display_name=identity.display_name,
        status=identity.status,
        preferred_source=identity.preferred_source,
    )


def _is_preferred_source(shop: Shop) -> bool:
    identity = shop.shop_identity
    return identity is not None and identity.preferred_source == shop.source
