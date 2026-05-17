from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from stroyhub.core.config import settings
from stroyhub.models import Category, PriceSnapshot, ScrapeRun, Shop, SourceProduct
from stroyhub.parsers.unicom import UnicomClient
from stroyhub.scraping import persist_unicom_scrape_result, scrape_unicom_category


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


def test_scrape_unicom_category_collects_and_parses_products() -> None:
    client = UnicomClient(client=httpx.Client(transport=httpx.MockTransport(_unicom_handler)))
    parsed_at = datetime(2026, 5, 17, 10, 0, tzinfo=UTC)

    result = scrape_unicom_category(
        category_uuid="category-scrape-test",
        client=client,
        limit=2,
        parsed_at=parsed_at,
    )

    assert result.products_count == 3
    assert result.pages_seen == 2
    assert result.products_seen == 3
    assert len(result.products) == 3
    assert result.products[0].source == "unicom"
    assert result.products[0].price == Decimal("100.00")
    assert result.products[0].parsed_at == parsed_at
    assert result.completeness == "complete"


def test_persist_unicom_scrape_result_upserts_products_and_appends_price_snapshots(
    db_session: Session,
) -> None:
    client = UnicomClient(client=httpx.Client(transport=httpx.MockTransport(_unicom_handler)))
    first_result = scrape_unicom_category(
        category_uuid="category-persist-test",
        client=client,
        limit=2,
        parsed_at=datetime(2026, 5, 17, 10, 0, tzinfo=UTC),
    )
    first_persist = persist_unicom_scrape_result(
        db_session,
        first_result,
        shop_name="Юником Test",
        finished_at=datetime(2026, 5, 17, 10, 1, tzinfo=UTC),
    )
    second_result = scrape_unicom_category(
        category_uuid="category-persist-test",
        client=client,
        limit=2,
        parsed_at=datetime(2026, 5, 17, 11, 0, tzinfo=UTC),
    )
    second_persist = persist_unicom_scrape_result(
        db_session,
        second_result,
        shop_name="Юником Test",
        finished_at=datetime(2026, 5, 17, 11, 1, tzinfo=UTC),
    )

    shop = db_session.scalar(select(Shop).where(Shop.source == "unicom", Shop.source_id == "uc"))
    source_product_count = db_session.scalar(
        select(func.count()).select_from(SourceProduct).where(SourceProduct.shop_id == shop.id)
    )
    snapshot_count = db_session.scalar(
        select(func.count())
        .select_from(PriceSnapshot)
        .join(SourceProduct)
        .where(SourceProduct.shop_id == shop.id)
    )
    scrape_run_count = db_session.scalar(
        select(func.count()).select_from(ScrapeRun).where(ScrapeRun.shop_id == shop.id)
    )
    cement_product = db_session.scalar(
        select(SourceProduct).where(SourceProduct.source_product_id == "unicom-product-1")
    )
    cement_category = db_session.scalar(select(Category).where(Category.slug == "cement"))
    mixes_category = db_session.scalar(select(Category).where(Category.slug == "mixes_aggregates"))
    scrape_run = db_session.get(ScrapeRun, first_persist.scrape_run_id)

    assert shop is not None
    assert shop.name == "Юником Test"
    assert shop.url == "https://unicom-ykt.ru/"
    assert shop.scrape_status == "success"
    assert first_persist.shop_id == second_persist.shop_id == shop.id
    assert first_persist.source_products_saved == 3
    assert first_persist.price_snapshots_saved == 3
    assert second_persist.source_products_saved == 3
    assert second_persist.price_snapshots_saved == 3
    assert source_product_count == 3
    assert snapshot_count == 6
    assert scrape_run_count == 2
    assert scrape_run is not None
    assert scrape_run.raw["category_uuid"] == "category-persist-test"
    assert scrape_run.raw["pages_seen"] == 2
    assert scrape_run.raw["products_count"] == 3
    assert mixes_category is not None
    assert cement_category is not None
    assert cement_category.parent_id == mixes_category.id
    assert cement_product is not None
    assert cement_product.category_id == cement_category.id


def test_persist_unicom_scrape_result_marks_partial_run_but_failed_shop_status(
    db_session: Session,
) -> None:
    client = UnicomClient(client=httpx.Client(transport=httpx.MockTransport(_partial_handler)))
    result = scrape_unicom_category(
        category_uuid="category-partial-test",
        client=client,
        limit=1,
        max_pages=2,
        parsed_at=datetime(2026, 5, 17, 10, 0, tzinfo=UTC),
    )

    persisted = persist_unicom_scrape_result(
        db_session,
        result,
        shop_name="Юником Partial Test",
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


def _unicom_handler(request: httpx.Request) -> httpx.Response:
    page_number = int(request.url.params["page"])
    if page_number == 1:
        products = [
            _product(
                product_id="unicom-product-1",
                name="Цемент М500",
                category="Цемент",
                price=100,
            ),
            _product(
                product_id="unicom-product-2",
                name="Клей плиточный",
                category="Сухие клеевые смеси",
                price=200,
            ),
        ]
    elif page_number == 2:
        products = [
            _product(
                product_id="unicom-product-3",
                name="Кирпич строительный",
                category="Блоки строительные",
                price=300,
            )
        ]
    else:
        products = []

    return httpx.Response(
        200,
        json={
            "products": products,
            "pages": 2,
            "productsCount": 3,
            "stocks": [],
            "filters": [],
        },
    )


def _partial_handler(_: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "products": [
                _product(
                    product_id="unicom-product-1",
                    name="Цемент М500",
                    category="Цемент",
                    price=100,
                )
            ],
            "pages": 10,
            "productsCount": 10,
            "stocks": [],
            "filters": [],
        },
    )


def _product(
    *,
    product_id: str,
    name: str,
    category: str,
    price: int,
) -> dict[str, object]:
    return {
        "uuid": product_id,
        "name": name,
        "category": category,
        "price": f"{price}.00",
        "price_unit": "шт.",
        "created_date": None,
    }
