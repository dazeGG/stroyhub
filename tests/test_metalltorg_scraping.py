from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from stroyhub.core.config import settings
from stroyhub.db import ShopRepository, ShopUpsert
from stroyhub.models import PriceSnapshot, ScrapeRun, Shop, SourceProduct
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


def _fixture_fetch(url: str, timeout: float) -> str:
    assert timeout > 0
    if url == "https://metalltorg.biz/catalog/stroitelnye_materialy_1/kirpich/":
        return (FIXTURES_DIR / "category-kirpich-page1.html").read_text()
    if url == "https://metalltorg.biz/catalog/stroitelnye_materialy_1/kirpich/120420/":
        return (FIXTURES_DIR / "product-kirpich-120420.html").read_text()
    raise AssertionError(f"unexpected fixture URL: {url}")
