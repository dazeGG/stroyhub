from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from stroyhub.core.config import settings
from stroyhub.db import ShopRepository, ShopUpsert
from stroyhub.models import PriceSnapshot, ScrapeRun, Shop, SourceProduct
from stroyhub.parsers.common import ParsedProduct
from stroyhub.parsers.metalltorg.parser import MetalltorgListingPage
from stroyhub.scraping import (
    persist_metalltorg_scrape_failure,
    persist_metalltorg_scrape_result,
    scrape_metalltorg_category,
    scrape_metalltorg_shop,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "metalltorg"


@pytest.fixture
def db_session() -> Iterator[Session]:
    engine = create_engine(settings.database_url, connect_args={"connect_timeout": 1})

    try:
        connection = engine.connect()
    except OperationalError:
        engine.dispose()
        pytest.skip("PostgreSQL is not available")

    transaction = connection.begin()
    session = Session(bind=connection, autoflush=False, expire_on_commit=False)
    session.execute(
        text(
            "TRUNCATE price_snapshots, source_products, scrape_runs, shops, "
            "shop_identities, categories RESTART IDENTITY CASCADE"
        )
    )

    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()


def test_scrape_metalltorg_category_collects_fixture_products() -> None:
    result = scrape_metalltorg_category(
        start_url="https://metalltorg.biz/catalog/stroitelnye_materialy_1/kirpich/",
        fetch=_fixture_fetch,
        parsed_at=datetime(2026, 5, 18, 10, 0, tzinfo=UTC),
    )

    assert result.completeness == "complete"
    assert result.stop_reason == "complete"
    assert result.pages_seen == 1
    assert result.products_seen == 1
    assert result.priced_products == 1
    assert result.products[0].source == "metalltorg"


def test_scrape_metalltorg_category_completes_when_reported_total_is_seen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_at = datetime(2026, 5, 18, 10, 0, tzinfo=UTC)

    def fake_parse_listing_page(
        html: str,
        *,
        page_url: str,
        parsed_at: datetime,
    ) -> MetalltorgListingPage:
        return MetalltorgListingPage(
            products=[
                _parsed_product("one", parsed_at=parsed_at),
                _parsed_product("two", parsed_at=parsed_at),
            ],
            next_page_urls=[
                "https://metalltorg.biz/catalog/stroitelnye_materialy_1/?PAGEN_1=2",
                "https://metalltorg.biz/catalog/stroitelnye_materialy_1/?PAGEN_1=3",
            ],
            total_count=2,
            raw={"page_url": page_url, "html": html},
        )

    monkeypatch.setattr(
        "stroyhub.scraping.metalltorg.parse_listing_page",
        fake_parse_listing_page,
    )

    result = scrape_metalltorg_category(
        start_url="https://metalltorg.biz/catalog/stroitelnye_materialy_1/",
        max_pages=1,
        fetch=lambda url, timeout: "<html></html>",
        parsed_at=observed_at,
    )

    assert result.completeness == "complete"
    assert result.stop_reason == "complete"
    assert result.pages_seen == 1
    assert result.products_seen == 2
    assert result.total_count == 2
    assert result.next_pages_seen == 0


def test_persist_metalltorg_scrape_result_saves_products_and_snapshots(
    db_session: Session,
) -> None:
    result = scrape_metalltorg_category(
        start_url="https://metalltorg.biz/catalog/stroitelnye_materialy_1/kirpich/",
        fetch=_fixture_fetch,
        parsed_at=datetime(2026, 5, 18, 10, 0, tzinfo=UTC),
    )

    persisted = persist_metalltorg_scrape_result(
        db_session,
        result,
        finished_at=datetime(2026, 5, 18, 10, 1, tzinfo=UTC),
    )

    shop = db_session.get(Shop, persisted.shop_id)
    source_product_count = db_session.scalar(
        select(func.count()).select_from(SourceProduct).where(SourceProduct.shop_id == shop.id)
    )
    snapshot_count = db_session.scalar(
        select(func.count())
        .select_from(PriceSnapshot)
        .join(SourceProduct)
        .where(SourceProduct.shop_id == shop.id)
    )
    scrape_run = db_session.get(ScrapeRun, persisted.scrape_run_id)

    assert shop is not None
    assert shop.source == "metalltorg"
    assert shop.source_type == "official_html"
    assert shop.scrape_status == "success"
    assert persisted.source_products_saved == 1
    assert persisted.price_snapshots_saved == 1
    assert source_product_count == 1
    assert snapshot_count == 1
    assert scrape_run is not None
    assert scrape_run.status == "success"
    assert scrape_run.items_seen == 1


def test_scrape_metalltorg_shop_preserves_seeded_config(db_session: Session) -> None:
    shop = ShopRepository(db_session).upsert(
        ShopUpsert(
            source="metalltorg",
            source_id="metalltorg-yakutsk",
            source_type="official_html",
            name="Металл Торг",
            raw={
                "category_urls": [
                    "https://metalltorg.biz/catalog/stroitelnye_materialy_1/kirpich/"
                ],
                "max_pages": 1,
                "timeout": 5.0,
            },
        )
    )

    result = scrape_metalltorg_shop(
        db_session,
        shop,
        fetch=_fixture_fetch,
        finished_at=datetime(2026, 5, 18, 10, 0, tzinfo=UTC),
    )

    assert result.categories_seen == 1
    assert result.categories_partial == 0
    assert result.products_seen == 1
    assert result.scrape_status == "success"
    assert result.details_fetched == 1
    persisted_product = db_session.scalar(
        select(SourceProduct).where(SourceProduct.shop_id == shop.id)
    )
    assert persisted_product is not None
    assert persisted_product.category_raw == "Строительные материалы/Кирпич"
    assert persisted_product.description is not None
    assert "Кирпич огнеупорный полнотелый ШБ-5" in persisted_product.description
    assert persisted_product.fingerprint is not None
    assert shop.raw["category_urls"] == [
        "https://metalltorg.biz/catalog/stroitelnye_materialy_1/kirpich/"
    ]
    assert shop.raw["max_pages"] == 1
    assert shop.raw["timeout"] == 5.0


def test_scrape_metalltorg_category_marks_page_failures_partial() -> None:
    def failing_fetch(url: str, timeout: float) -> str:
        raise httpx.ConnectError("offline")

    result = scrape_metalltorg_category(
        start_url="https://metalltorg.biz/catalog/stroitelnye_materialy_1/kirpich/",
        fetch=failing_fetch,
    )

    assert result.completeness == "partial"
    assert result.stop_reason == "page_failures"
    assert result.failures == 1
    assert result.products_seen == 0


def test_persist_metalltorg_scrape_failure_records_failed_run(db_session: Session) -> None:
    shop = ShopRepository(db_session).upsert(
        ShopUpsert(
            source="metalltorg",
            source_id="metalltorg-yakutsk",
            source_type="official_html",
            name="Металл Торг Failure",
            raw={"category_urls": ["https://metalltorg.biz/catalog/test/"]},
        )
    )

    scrape_run_id = persist_metalltorg_scrape_failure(
        db_session,
        shop,
        error="selector changed",
        failed_at=datetime(2026, 5, 18, 10, 0, tzinfo=UTC),
    )

    scrape_run = db_session.get(ScrapeRun, scrape_run_id)

    assert scrape_run is not None
    assert scrape_run.status == "failed"
    assert scrape_run.source == "metalltorg"
    assert scrape_run.error == "selector changed"


def _parsed_product(source_product_id: str, *, parsed_at: datetime) -> ParsedProduct:
    return ParsedProduct(
        source="metalltorg",
        shop_source_id="metalltorg-yakutsk",
        source_product_id=source_product_id,
        title=f"Product {source_product_id}",
        normalized_title=f"product {source_product_id}",
        fingerprint=f"fingerprint-{source_product_id}",
        description=None,
        category_raw="Строительные материалы",
        unit_raw="шт",
        price=Decimal("100.00"),
        currency="RUB",
        image_url=None,
        source_updated_at=None,
        raw={"product_url": f"https://example.test/{source_product_id}"},
        parsed_at=parsed_at,
    )


def _fixture_fetch(url: str, timeout: float) -> str:
    assert timeout > 0
    if url == "https://metalltorg.biz/catalog/stroitelnye_materialy_1/kirpich/":
        return (FIXTURES_DIR / "category-kirpich-page1.html").read_text()
    if url == "https://metalltorg.biz/catalog/stroitelnye_materialy_1/kirpich/120420/":
        return (FIXTURES_DIR / "product-kirpich-120420.html").read_text()
    raise AssertionError(f"unexpected fixture URL: {url}")
