from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stroyhub.models.tables import PriceSnapshot, ScrapeRun, Shop, SourceProduct

JsonObject = dict[str, Any]


@dataclass(frozen=True, kw_only=True)
class ShopUpsert:
    source: str
    source_id: str
    name: str
    address: str | None = None
    url: str | None = None
    raw: JsonObject | None = None
    last_scraped_at: datetime | None = None
    next_scrape_at: datetime | None = None
    scrape_interval: int | None = None
    scrape_status: str | None = None
    error_count: int | None = None


@dataclass(frozen=True, kw_only=True)
class SourceProductUpsert:
    shop_id: int
    source: str
    title: str
    normalized_title: str
    source_product_id: str | None = None
    fingerprint: str | None = None
    description: str | None = None
    category_id: int | None = None
    category_raw: str | None = None
    unit_raw: str | None = None
    image_url: str | None = None
    source_updated_at: datetime | None = None
    raw: JsonObject | None = None
    observed_at: datetime | None = None
    is_active: bool = True


@dataclass(frozen=True, kw_only=True)
class PriceSnapshotCreate:
    source_product_id: int
    price: Decimal | None
    currency: str = "RUB"
    unit_raw: str | None = None
    source_updated_at: datetime | None = None
    parsed_at: datetime | None = None
    raw: JsonObject | None = None


@dataclass(frozen=True, kw_only=True)
class ScrapeRunCreate:
    source: str
    shop_id: int | None = None
    status: str = "running"
    started_at: datetime | None = None
    raw: JsonObject | None = None


class ShopRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_source_id(self, *, source: str, source_id: str) -> Shop | None:
        statement = select(Shop).where(Shop.source == source, Shop.source_id == source_id)
        return self._session.scalar(statement)

    def upsert(self, data: ShopUpsert) -> Shop:
        shop = self.get_by_source_id(source=data.source, source_id=data.source_id)

        if shop is None:
            shop = Shop(
                source=data.source,
                source_id=data.source_id,
                name=data.name,
            )
            self._session.add(shop)

        shop.name = data.name
        shop.address = data.address
        shop.url = data.url
        shop.raw = data.raw
        shop.last_scraped_at = data.last_scraped_at
        shop.next_scrape_at = data.next_scrape_at

        if data.scrape_interval is not None:
            shop.scrape_interval = data.scrape_interval
        if data.scrape_status is not None:
            shop.scrape_status = data.scrape_status
        if data.error_count is not None:
            shop.error_count = data.error_count

        self._session.flush()
        return shop

    def list_due_for_scraping(
        self,
        *,
        now: datetime,
        source: str | None = None,
        limit: int | None = None,
    ) -> list[Shop]:
        statement = select(Shop).where(
            Shop.scrape_status != "disabled",
            (Shop.next_scrape_at.is_(None) | (Shop.next_scrape_at <= now)),
        )
        if source is not None:
            statement = statement.where(Shop.source == source)
        statement = statement.order_by(Shop.next_scrape_at.asc().nullsfirst(), Shop.id.asc())
        if limit is not None:
            statement = statement.limit(limit)

        return list(self._session.scalars(statement))


class SourceProductRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_for_upsert(self, data: SourceProductUpsert) -> SourceProduct | None:
        if data.source_product_id is None and data.fingerprint is None:
            raise ValueError("source products require source_product_id or fingerprint for upsert")

        if data.source_product_id is not None:
            statement = select(SourceProduct).where(
                SourceProduct.source == data.source,
                SourceProduct.shop_id == data.shop_id,
                SourceProduct.source_product_id == data.source_product_id,
            )
            product = self._session.scalar(statement)
            if product is not None:
                return product

        if data.fingerprint is not None:
            statement = select(SourceProduct).where(
                SourceProduct.source == data.source,
                SourceProduct.shop_id == data.shop_id,
                SourceProduct.fingerprint == data.fingerprint,
            )
            return self._session.scalar(statement)

        return None

    def upsert(self, data: SourceProductUpsert) -> SourceProduct:
        product = self.get_for_upsert(data)
        observed_at = data.observed_at

        if product is None:
            product = SourceProduct(
                shop_id=data.shop_id,
                source=data.source,
                title=data.title,
                normalized_title=data.normalized_title,
            )
            if observed_at is not None:
                product.first_seen_at = observed_at
            self._session.add(product)

        product.source_product_id = data.source_product_id
        product.fingerprint = data.fingerprint
        product.title = data.title
        product.normalized_title = data.normalized_title
        product.description = data.description
        product.category_id = data.category_id
        product.category_raw = data.category_raw
        product.unit_raw = data.unit_raw
        product.image_url = data.image_url
        product.source_updated_at = data.source_updated_at
        product.raw = data.raw
        product.is_active = data.is_active

        if observed_at is not None:
            product.last_seen_at = observed_at

        self._session.flush()
        return product


class PriceSnapshotRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, data: PriceSnapshotCreate) -> PriceSnapshot:
        snapshot = PriceSnapshot(
            source_product_id=data.source_product_id,
            price=data.price,
            currency=data.currency,
            unit_raw=data.unit_raw,
            source_updated_at=data.source_updated_at,
            raw=data.raw,
        )

        if data.parsed_at is not None:
            snapshot.parsed_at = data.parsed_at

        self._session.add(snapshot)
        self._session.flush()
        return snapshot


class ScrapeRunRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def start(self, data: ScrapeRunCreate) -> ScrapeRun:
        scrape_run = ScrapeRun(
            source=data.source,
            shop_id=data.shop_id,
            status=data.status,
            raw=data.raw,
        )

        if data.started_at is not None:
            scrape_run.started_at = data.started_at

        self._session.add(scrape_run)
        self._session.flush()
        return scrape_run

    def finish(
        self,
        scrape_run: ScrapeRun,
        *,
        status: str,
        items_seen: int,
        items_saved: int,
        finished_at: datetime,
        error: str | None = None,
        raw: JsonObject | None = None,
    ) -> ScrapeRun:
        scrape_run.status = status
        scrape_run.items_seen = items_seen
        scrape_run.items_saved = items_saved
        scrape_run.finished_at = finished_at
        scrape_run.error = error
        if raw is not None:
            scrape_run.raw = raw

        self._session.flush()
        return scrape_run
