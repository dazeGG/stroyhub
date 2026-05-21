from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from stroyhub.models.tables import Shop


@dataclass(frozen=True, kw_only=True)
class ShopListFilters:
    source: str | None = None
    status: str | None = None


@dataclass(frozen=True, kw_only=True)
class ShopListItem:
    id: int
    source: str
    source_id: str
    name: str
    address: str | None
    scrape_status: str
    last_scraped_at: datetime | None
    next_scrape_at: datetime | None


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

        return [
            ShopListItem(
                id=shop.id,
                source=shop.source,
                source_id=shop.source_id,
                name=shop.name,
                address=shop.address,
                scrape_status=shop.scrape_status,
                last_scraped_at=shop.last_scraped_at,
                next_scrape_at=shop.next_scrape_at,
            )
            for shop in self._session.scalars(statement)
        ]
