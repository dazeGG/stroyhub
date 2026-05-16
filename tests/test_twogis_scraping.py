from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from stroyhub.core.config import settings
from stroyhub.models import PriceSnapshot, ScrapeRun, Shop, SourceProduct
from stroyhub.parsers.twogis import TwogisClient
from stroyhub.scraping import persist_twogis_scrape_result, scrape_twogis_branch


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


def test_scrape_twogis_branch_collects_and_parses_products() -> None:
    client = TwogisClient(client=httpx.Client(transport=httpx.MockTransport(_twogis_handler)))
    parsed_at = datetime(2026, 5, 17, 10, 0, tzinfo=UTC)

    result = scrape_twogis_branch(
        branch_id="branch-scrape-test",
        client=client,
        page_size=2,
        parsed_at=parsed_at,
    )

    assert result.total == 3
    assert result.pages_seen == 2
    assert result.items_seen == 3
    assert len(result.products) == 3
    assert result.products[0].price == Decimal("100")
    assert result.products[0].parsed_at == parsed_at
    assert result.completeness == "complete"


def test_persist_twogis_scrape_result_upserts_products_and_appends_price_snapshots(
    db_session: Session,
) -> None:
    client = TwogisClient(client=httpx.Client(transport=httpx.MockTransport(_twogis_handler)))
    first_result = scrape_twogis_branch(
        branch_id="branch-persist-test",
        client=client,
        page_size=2,
        parsed_at=datetime(2026, 5, 17, 10, 0, tzinfo=UTC),
    )
    first_persist = persist_twogis_scrape_result(
        db_session,
        first_result,
        shop_name="Persist Test Shop",
        finished_at=datetime(2026, 5, 17, 10, 1, tzinfo=UTC),
    )
    second_result = scrape_twogis_branch(
        branch_id="branch-persist-test",
        client=client,
        page_size=2,
        parsed_at=datetime(2026, 5, 17, 11, 0, tzinfo=UTC),
    )
    second_persist = persist_twogis_scrape_result(
        db_session,
        second_result,
        shop_name="Persist Test Shop",
        finished_at=datetime(2026, 5, 17, 11, 1, tzinfo=UTC),
    )

    shop = db_session.scalar(
        select(Shop).where(Shop.source == "2gis", Shop.source_id == "branch-persist-test")
    )
    source_product_count = db_session.scalar(
        select(func.count()).select_from(SourceProduct).where(SourceProduct.shop_id == shop.id)
    )
    snapshot_count = db_session.scalar(select(func.count()).select_from(PriceSnapshot))
    scrape_run_count = db_session.scalar(select(func.count()).select_from(ScrapeRun))

    assert shop is not None
    assert shop.name == "Persist Test Shop"
    assert shop.scrape_status == "success"
    assert first_persist.shop_id == second_persist.shop_id == shop.id
    assert first_persist.source_products_saved == 3
    assert first_persist.price_snapshots_saved == 3
    assert second_persist.source_products_saved == 3
    assert second_persist.price_snapshots_saved == 3
    assert source_product_count == 3
    assert snapshot_count == 6
    assert scrape_run_count == 2


def test_persist_twogis_scrape_result_marks_partial_run_but_failed_shop_status(
    db_session: Session,
) -> None:
    client = TwogisClient(client=httpx.Client(transport=httpx.MockTransport(_partial_handler)))
    result = scrape_twogis_branch(
        branch_id="branch-partial-test",
        client=client,
        page_size=1,
        parsed_at=datetime(2026, 5, 17, 10, 0, tzinfo=UTC),
    )

    persisted = persist_twogis_scrape_result(
        db_session,
        result,
        shop_name="Partial Test Shop",
        finished_at=datetime(2026, 5, 17, 10, 1, tzinfo=UTC),
    )

    shop = db_session.get(Shop, persisted.shop_id)
    scrape_run = db_session.get(ScrapeRun, persisted.scrape_run_id)

    assert result.completeness == "partial"
    assert persisted.scrape_status == "partial"
    assert shop is not None
    assert shop.scrape_status == "failed"
    assert scrape_run is not None
    assert scrape_run.status == "partial"


def _twogis_handler(request: httpx.Request) -> httpx.Response:
    page_number = int(request.url.params["page"])
    if page_number == 1:
        items = [
            _item(product_id="product-1", name="Цемент М500", price=100),
            _item(product_id="product-2", name="Песок мытый", price=200),
        ]
    elif page_number == 2:
        items = [_item(product_id="product-3", name="Кирпич", price=300)]
    else:
        items = []

    return httpx.Response(
        200,
        json={
            "meta": {"code": 200},
            "result": {
                "total": 3,
                "updated_at": "Обновлено 13 января 2026",
                "items": items,
            },
        },
    )


def _partial_handler(request: httpx.Request) -> httpx.Response:
    page_number = int(request.url.params["page"])
    items = (
        [_item(product_id="product-1", name="Цемент М500", price=100)]
        if page_number == 1
        else []
    )

    return httpx.Response(
        200,
        json={
            "meta": {"code": 200},
            "result": {
                "total": 3,
                "updated_at": "Обновлено 13 января 2026",
                "items": items,
            },
        },
    )


def _item(*, product_id: str, name: str, price: int) -> dict[str, object]:
    return {
        "product": {
            "id": product_id,
            "name": name,
            "description": "",
            "images": [f"https://example.test/{product_id}.jpg"],
            "categories": [{"label": "Стройматериалы"}],
        },
        "offer": {
            "price": price,
            "currency": "RUB",
            "price_value": {"fixed": {"value": price, "currency": "RUB"}},
        },
    }
