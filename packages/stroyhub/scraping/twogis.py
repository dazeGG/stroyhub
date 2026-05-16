from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from stroyhub.db.repositories import (
    PriceSnapshotCreate,
    PriceSnapshotRepository,
    ScrapeRunCreate,
    ScrapeRunRepository,
    ShopRepository,
    ShopUpsert,
    SourceProductRepository,
    SourceProductUpsert,
)
from stroyhub.parsers.common import JsonObject, ParsedProduct
from stroyhub.parsers.twogis import TwogisBranchItems, TwogisClient, parse_product_items

TWOGIS_SOURCE = "2gis"


@dataclass(frozen=True, kw_only=True)
class TwogisScrapeResult:
    branch_id: str
    page_size: int
    total: int | None
    pages_seen: int
    items_seen: int
    pinned_items_seen: int
    products: list[ParsedProduct]
    completeness: str
    stop_reason: str
    branch_items: TwogisBranchItems


@dataclass(frozen=True, kw_only=True)
class TwogisPersistResult:
    shop_id: int
    scrape_run_id: int
    source_products_saved: int
    price_snapshots_saved: int
    scrape_status: str


def scrape_twogis_branch(
    *,
    branch_id: str,
    client: TwogisClient | None = None,
    page_size: int = 50,
    max_pages: int = 100,
    locale: str = "ru_RU",
    parsed_at: datetime | None = None,
) -> TwogisScrapeResult:
    twogis_client = client or TwogisClient()
    branch_items = twogis_client.fetch_branch_items(
        branch_id=branch_id,
        page_size=page_size,
        max_pages=max_pages,
        locale=locale,
    )
    observed_at = parsed_at or datetime.now(UTC)

    products = parse_product_items(
        branch_items.items,
        branch_id=branch_id,
        source_updated_at_raw=_first_updated_at(branch_items),
        parsed_at=observed_at,
    )

    return TwogisScrapeResult(
        branch_id=branch_id,
        page_size=page_size,
        total=branch_items.total,
        pages_seen=len(branch_items.pages),
        items_seen=len(branch_items.items),
        pinned_items_seen=len(branch_items.pinned_items),
        products=products,
        completeness=branch_items.completeness,
        stop_reason=branch_items.stop_reason,
        branch_items=branch_items,
    )


def persist_twogis_scrape_result(
    session: Session,
    result: TwogisScrapeResult,
    *,
    shop_name: str | None = None,
    finished_at: datetime | None = None,
) -> TwogisPersistResult:
    completed_at = finished_at or datetime.now(UTC)
    scrape_run_status = "success" if result.completeness in {"complete", "empty"} else "partial"
    shop_status = "success" if scrape_run_status == "success" else "failed"

    shop = ShopRepository(session).upsert(
        ShopUpsert(
            source=TWOGIS_SOURCE,
            source_id=result.branch_id,
            name=shop_name or f"2GIS branch {result.branch_id}",
            raw=_shop_raw(result),
            last_scraped_at=completed_at,
            scrape_status=shop_status,
        )
    )
    scrape_run_repository = ScrapeRunRepository(session)
    scrape_run = scrape_run_repository.start(
        ScrapeRunCreate(
            source=TWOGIS_SOURCE,
            shop_id=shop.id,
            started_at=_first_parsed_at(result.products) or completed_at,
            raw=_scrape_run_raw(result),
        )
    )

    product_repository = SourceProductRepository(session)
    price_repository = PriceSnapshotRepository(session)
    source_products_saved = 0
    price_snapshots_saved = 0

    for product in result.products:
        source_product = product_repository.upsert(
            SourceProductUpsert(
                shop_id=shop.id,
                source=product.source,
                source_product_id=product.source_product_id,
                fingerprint=product.fingerprint,
                title=product.title,
                normalized_title=product.normalized_title,
                description=product.description,
                category_raw=product.category_raw,
                unit_raw=product.unit_raw,
                image_url=product.image_url,
                source_updated_at=product.source_updated_at,
                raw=product.raw,
                observed_at=product.parsed_at,
            )
        )
        source_products_saved += 1

        price_repository.add(
            PriceSnapshotCreate(
                source_product_id=source_product.id,
                price=product.price,
                currency=product.currency,
                unit_raw=product.unit_raw,
                source_updated_at=product.source_updated_at,
                parsed_at=product.parsed_at,
                raw=product.raw,
            )
        )
        price_snapshots_saved += 1

    scrape_run_repository.finish(
        scrape_run,
        status=scrape_run_status,
        items_seen=result.items_seen,
        items_saved=source_products_saved,
        finished_at=completed_at,
        raw=_scrape_run_raw(result),
    )

    return TwogisPersistResult(
        shop_id=shop.id,
        scrape_run_id=scrape_run.id,
        source_products_saved=source_products_saved,
        price_snapshots_saved=price_snapshots_saved,
        scrape_status=scrape_run_status,
    )


def _first_updated_at(result: TwogisBranchItems) -> str | None:
    for page in result.pages:
        if page.updated_at_raw is not None:
            return page.updated_at_raw
    return None


def _first_parsed_at(products: list[ParsedProduct]) -> datetime | None:
    if not products:
        return None
    return products[0].parsed_at


def _shop_raw(result: TwogisScrapeResult) -> JsonObject:
    return {
        "source": TWOGIS_SOURCE,
        "branch_id": result.branch_id,
        "total": result.total,
        "pages_seen": result.pages_seen,
        "items_seen": result.items_seen,
        "pinned_items_seen": result.pinned_items_seen,
        "completeness": result.completeness,
        "stop_reason": result.stop_reason,
    }


def _scrape_run_raw(result: TwogisScrapeResult) -> JsonObject:
    return {
        "branch_id": result.branch_id,
        "page_size": result.page_size,
        "total": result.total,
        "pages_seen": result.pages_seen,
        "items_seen": result.items_seen,
        "products_parsed": len(result.products),
        "pinned_items_seen": result.pinned_items_seen,
        "completeness": result.completeness,
        "stop_reason": result.stop_reason,
    }
