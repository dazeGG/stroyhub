from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from stroyhub.core.config import settings
from stroyhub.db import (
    PriceSnapshotCreate,
    PriceSnapshotRepository,
    ShopRepository,
    ShopUpsert,
    SourceProductRepository,
    SourceProductUpsert,
)
from stroyhub.models import Category

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


def test_products_endpoint_returns_latest_price_and_shop(
    client: TestClient, db_session: Session
) -> None:
    shop = ShopRepository(db_session).upsert(
        ShopUpsert(source="2gis", source_id="branch-api-1", name="Build Shop")
    )
    product = SourceProductRepository(db_session).upsert(
        SourceProductUpsert(
            shop_id=shop.id,
            source="2gis",
            source_product_id="cement-api-1",
            title="API Unique Cement M500",
            normalized_title="api unique cement m500",
            category_raw="Catalog / Cement",
            unit_raw="bag",
            observed_at=datetime(2026, 5, 17, 8, 0, tzinfo=UTC),
        )
    )
    prices = PriceSnapshotRepository(db_session)
    prices.add(
        PriceSnapshotCreate(
            source_product_id=product.id,
            price=Decimal("650.00"),
            parsed_at=datetime(2026, 5, 17, 8, 1, tzinfo=UTC),
        )
    )
    prices.add(
        PriceSnapshotCreate(
            source_product_id=product.id,
            price=Decimal("700.00"),
            parsed_at=datetime(2026, 5, 17, 9, 1, tzinfo=UTC),
            source_updated_at=datetime(2026, 5, 17, 9, 0, tzinfo=UTC),
        )
    )

    response = client.get("/products", params={"q": "api unique cement"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["limit"] == 50
    assert payload["offset"] == 0
    assert len(payload["items"]) == 1
    item = payload["items"][0]
    assert item["id"] == product.id
    assert item["title"] == "API Unique Cement M500"
    assert item["shop"] == {
        "id": shop.id,
        "source": "2gis",
        "source_id": "branch-api-1",
        "name": "Build Shop",
    }
    assert item["latest_price"]["price"] == "700.00"
    assert item["latest_price"]["currency"] == "RUB"
    assert item["latest_price"]["source_updated_at"] == "2026-05-17T09:00:00Z"
    assert item["latest_price"]["parsed_at"] == "2026-05-17T09:01:00Z"


def test_products_endpoint_filters_by_search_shop_and_category(
    client: TestClient, db_session: Session
) -> None:
    matching_shop = ShopRepository(db_session).upsert(
        ShopUpsert(source="2gis", source_id="branch-api-2", name="Matching Shop")
    )
    other_shop = ShopRepository(db_session).upsert(
        ShopUpsert(source="2gis", source_id="branch-api-3", name="Other Shop")
    )
    matching_category = Category(slug="api-brick", name="Brick")
    other_category = Category(slug="api-other", name="Other")
    db_session.add_all([matching_category, other_category])
    db_session.flush()

    matching_product = SourceProductRepository(db_session).upsert(
        SourceProductUpsert(
            shop_id=matching_shop.id,
            source="2gis",
            source_product_id="brick-api-1",
            title="Red Brick",
            normalized_title="red brick",
            category_id=matching_category.id,
        )
    )
    SourceProductRepository(db_session).upsert(
        SourceProductUpsert(
            shop_id=other_shop.id,
            source="2gis",
            source_product_id="brick-api-2",
            title="Red Brick",
            normalized_title="red brick",
            category_id=other_category.id,
        )
    )

    response = client.get(
        "/products",
        params={
            "q": "brick",
            "shop": matching_shop.id,
            "category": matching_category.id,
            "limit": 10,
            "offset": 0,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert [item["id"] for item in payload["items"]] == [matching_product.id]
    assert payload["limit"] == 10
    assert payload["offset"] == 0


def test_products_endpoint_handles_empty_results(client: TestClient) -> None:
    response = client.get("/products", params={"q": "nothing-here"})

    assert response.status_code == 200
    assert response.json() == {"items": [], "limit": 50, "offset": 0}


def test_products_endpoint_treats_search_wildcards_as_literal_text(
    client: TestClient, db_session: Session
) -> None:
    shop = ShopRepository(db_session).upsert(
        ShopUpsert(source="2gis", source_id="branch-api-4", name="Wildcard Shop")
    )
    matching_product = SourceProductRepository(db_session).upsert(
        SourceProductUpsert(
            shop_id=shop.id,
            source="2gis",
            source_product_id="wildcard-api-1",
            title="Primer 100% coverage",
            normalized_title="primer 100% coverage",
        )
    )
    SourceProductRepository(db_session).upsert(
        SourceProductUpsert(
            shop_id=shop.id,
            source="2gis",
            source_product_id="wildcard-api-2",
            title="Regular Primer",
            normalized_title="regular primer",
        )
    )

    response = client.get("/products", params={"q": "100%"})

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [matching_product.id]


def test_product_price_history_endpoint_returns_ordered_snapshots(
    client: TestClient, db_session: Session
) -> None:
    shop = ShopRepository(db_session).upsert(
        ShopUpsert(source="2gis", source_id="branch-api-5", name="History Shop")
    )
    product = SourceProductRepository(db_session).upsert(
        SourceProductUpsert(
            shop_id=shop.id,
            source="2gis",
            source_product_id="history-api-1",
            title="Concrete Mix",
            normalized_title="concrete mix",
        )
    )
    repository = PriceSnapshotRepository(db_session)
    later = repository.add(
        PriceSnapshotCreate(
            source_product_id=product.id,
            price=Decimal("420.00"),
            unit_raw="bag",
            parsed_at=datetime(2026, 5, 17, 11, 0, tzinfo=UTC),
            source_updated_at=datetime(2026, 5, 17, 10, 50, tzinfo=UTC),
        )
    )
    earlier = repository.add(
        PriceSnapshotCreate(
            source_product_id=product.id,
            price=Decimal("400.00"),
            unit_raw="bag",
            parsed_at=datetime(2026, 5, 17, 10, 0, tzinfo=UTC),
            source_updated_at=datetime(2026, 5, 17, 9, 50, tzinfo=UTC),
        )
    )

    response = client.get(f"/products/{product.id}/prices")

    assert response.status_code == 200
    payload = response.json()
    assert payload["product_id"] == product.id
    assert [item["id"] for item in payload["items"]] == [earlier.id, later.id]
    assert payload["items"] == [
        {
            "id": earlier.id,
            "price": "400.00",
            "currency": "RUB",
            "unit_raw": "bag",
            "source_updated_at": "2026-05-17T09:50:00Z",
            "parsed_at": "2026-05-17T10:00:00Z",
        },
        {
            "id": later.id,
            "price": "420.00",
            "currency": "RUB",
            "unit_raw": "bag",
            "source_updated_at": "2026-05-17T10:50:00Z",
            "parsed_at": "2026-05-17T11:00:00Z",
        },
    ]


def test_product_price_history_endpoint_returns_404_for_missing_product(
    client: TestClient,
) -> None:
    response = client.get("/products/999999999/prices")

    assert response.status_code == 404
    assert response.json() == {"detail": "Source product not found"}
