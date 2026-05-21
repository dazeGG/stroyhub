from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from stroyhub.core.config import settings
from stroyhub.db import ShopRepository, ShopUpsert

from apps.api.main import create_app
from apps.api.products import get_session


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


@pytest.fixture
def client(db_session: Session) -> Iterator[TestClient]:
    app = create_app()

    def override_get_session() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_session] = override_get_session

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def test_shops_endpoint_lists_shops_without_raw_payload(
    client: TestClient, db_session: Session
) -> None:
    shop = ShopRepository(db_session).upsert(
        ShopUpsert(
            source="2gis",
            source_id="shops-api-1",
            name="API Shop",
            address="Yakutsk, Test Street 1",
            raw={"secret": "not exposed"},
            scrape_status="ok",
            last_scraped_at=datetime(2026, 5, 17, 8, 30, tzinfo=UTC),
        )
    )

    response = client.get("/shops", params={"source": "2gis", "status": "ok"})

    assert response.status_code == 200
    items = response.json()["items"]
    item = next(item for item in items if item["id"] == shop.id)
    assert item == {
        "id": shop.id,
        "source": "2gis",
        "source_id": "shops-api-1",
        "name": "API Shop",
        "address": "Yakutsk, Test Street 1",
        "scrape_status": "ok",
        "last_scraped_at": "2026-05-17T08:30:00Z",
    }
    assert "raw" not in item


def test_shops_endpoint_filters_by_source_and_status(
    client: TestClient, db_session: Session
) -> None:
    shops = ShopRepository(db_session)
    matching = shops.upsert(
        ShopUpsert(
            source="unicom",
            source_id="shops-api-2",
            name="Matching Shop",
            scrape_status="failed",
        )
    )
    shops.upsert(
        ShopUpsert(
            source="2gis",
            source_id="shops-api-3",
            name="Other Source Shop",
            scrape_status="failed",
        )
    )
    shops.upsert(
        ShopUpsert(
            source="unicom",
            source_id="shops-api-4",
            name="Other Status Shop",
            scrape_status="ok",
        )
    )

    response = client.get("/shops", params={"source": "unicom", "status": "failed"})

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [matching.id]


def test_shops_endpoint_handles_empty_results(client: TestClient) -> None:
    response = client.get(
        "/shops",
        params={"source": "source-with-no-shops", "status": "not-a-real-status"},
    )

    assert response.status_code == 200
    assert response.json() == {"items": []}
