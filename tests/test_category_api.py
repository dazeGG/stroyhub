from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from stroyhub.catalog.categories import CategoryTreeItem
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

import apps.api.categories as categories_api
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


def test_categories_endpoint_returns_tree_with_product_counts(
    client: TestClient, db_session: Session
) -> None:
    root = Category(slug="building-mixes", name="Building Mixes")
    other_root = Category(slug="tools", name="Tools")
    db_session.add_all([root, other_root])
    db_session.flush()

    cement = Category(slug="cement", name="Cement", parent_id=root.id)
    plaster = Category(slug="plaster", name="Plaster", parent_id=root.id)
    db_session.add_all([cement, plaster])
    db_session.flush()

    shop = ShopRepository(db_session).upsert(
        ShopUpsert(source="2gis", source_id="category-api-shop", name="Category Shop")
    )
    products = SourceProductRepository(db_session)
    products.upsert(
        SourceProductUpsert(
            shop_id=shop.id,
            source="2gis",
            source_product_id="cement-1",
            title="Cement M500",
            normalized_title="cement m500",
            category_id=cement.id,
        )
    )
    products.upsert(
        SourceProductUpsert(
            shop_id=shop.id,
            source="2gis",
            source_product_id="cement-2",
            title="Cement M400",
            normalized_title="cement m400",
            category_id=cement.id,
        )
    )
    products.upsert(
        SourceProductUpsert(
            shop_id=shop.id,
            source="2gis",
            source_product_id="plaster-1",
            title="Gypsum Plaster",
            normalized_title="gypsum plaster",
            category_id=plaster.id,
            is_active=False,
        )
    )

    response = client.get("/categories")

    assert response.status_code == 200
    items = response.json()["items"]
    root_item = next(item for item in items if item["id"] == root.id)
    assert root_item == {
        "id": root.id,
        "slug": "building-mixes",
        "name": "Building Mixes",
        "parent_id": None,
        "product_count": 2,
        "children": [
            {
                "id": cement.id,
                "slug": "cement",
                "name": "Cement",
                "parent_id": root.id,
                "product_count": 2,
                "children": [],
            },
            {
                "id": plaster.id,
                "slug": "plaster",
                "name": "Plaster",
                "parent_id": root.id,
                "product_count": 0,
                "children": [],
            },
        ],
    }

    other_root_item = next(item for item in items if item["id"] == other_root.id)
    assert other_root_item["product_count"] == 0
    assert other_root_item["children"] == []


def test_categories_endpoint_handles_empty_tree(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    class EmptyCategoryCatalog:
        def __init__(self, session: Session) -> None:
            self._session = session

        def list_tree(self) -> list[CategoryTreeItem]:
            return []

    monkeypatch.setattr(categories_api, "CategoryCatalog", EmptyCategoryCatalog)

    response = client.get("/categories")

    assert response.status_code == 200
    assert response.json() == {"items": []}


def test_category_price_summary_endpoint_aggregates_latest_prices(
    client: TestClient, db_session: Session
) -> None:
    category = Category(slug="summary-api-category", name="Summary API Category")
    db_session.add(category)
    db_session.flush()

    matching_shop = ShopRepository(db_session).upsert(
        ShopUpsert(source="2gis", source_id="summary-api-shop-1", name="Summary Shop")
    )
    other_shop = ShopRepository(db_session).upsert(
        ShopUpsert(source="unicom", source_id="summary-api-shop-2", name="Other Shop")
    )
    products = SourceProductRepository(db_session)
    priced_product = products.upsert(
        SourceProductUpsert(
            shop_id=matching_shop.id,
            source="2gis",
            source_product_id="summary-priced-product",
            title="Summary Priced Product",
            normalized_title="summary priced product",
            category_id=category.id,
        )
    )
    null_price_product = products.upsert(
        SourceProductUpsert(
            shop_id=matching_shop.id,
            source="2gis",
            source_product_id="summary-null-price-product",
            title="Summary Null Price Product",
            normalized_title="summary null price product",
            category_id=category.id,
        )
    )
    other_source_product = products.upsert(
        SourceProductUpsert(
            shop_id=other_shop.id,
            source="unicom",
            source_product_id="summary-other-source-product",
            title="Summary Other Source Product",
            normalized_title="summary other source product",
            category_id=category.id,
        )
    )
    prices = PriceSnapshotRepository(db_session)
    prices.add(
        PriceSnapshotCreate(
            source_product_id=priced_product.id,
            price=Decimal("8.00"),
            parsed_at=datetime(2026, 5, 17, 8, 0, tzinfo=UTC),
        )
    )
    prices.add(
        PriceSnapshotCreate(
            source_product_id=priced_product.id,
            price=Decimal("10.00"),
            parsed_at=datetime(2026, 5, 17, 9, 0, tzinfo=UTC),
        )
    )
    prices.add(
        PriceSnapshotCreate(
            source_product_id=null_price_product.id,
            price=None,
            parsed_at=datetime(2026, 5, 17, 9, 0, tzinfo=UTC),
        )
    )
    prices.add(
        PriceSnapshotCreate(
            source_product_id=other_source_product.id,
            price=Decimal("20.00"),
            parsed_at=datetime(2026, 5, 17, 9, 0, tzinfo=UTC),
        )
    )

    response = client.get(
        "/categories/price-summary",
        params={"source": "2gis", "shop": matching_shop.id},
    )

    assert response.status_code == 200
    item = next(
        item for item in response.json()["items"] if item["category_id"] == category.id
    )
    assert item == {
        "category_id": category.id,
        "category_slug": "summary-api-category",
        "category_name": "Summary API Category",
        "product_count": 2,
        "priced_product_count": 1,
        "min_price": "10.00",
        "avg_price": "10.00",
        "max_price": "10.00",
    }


def test_category_quality_endpoint_groups_uncategorized_products(
    client: TestClient, db_session: Session
) -> None:
    category = Category(slug="quality-api-category", name="Quality API Category")
    db_session.add(category)
    db_session.flush()

    matching_shop = ShopRepository(db_session).upsert(
        ShopUpsert(source="2gis", source_id="quality-api-shop-1", name="Quality Shop")
    )
    other_shop = ShopRepository(db_session).upsert(
        ShopUpsert(source="unicom", source_id="quality-api-shop-2", name="Other Quality Shop")
    )
    products = SourceProductRepository(db_session)
    products.upsert(
        SourceProductUpsert(
            shop_id=matching_shop.id,
            source="2gis",
            source_product_id="quality-categorized",
            title="Categorized Product",
            normalized_title="categorized product",
            category_id=category.id,
            category_raw="Raw A",
        )
    )
    products.upsert(
        SourceProductUpsert(
            shop_id=matching_shop.id,
            source="2gis",
            source_product_id="quality-uncategorized-1",
            title="Uncategorized First",
            normalized_title="uncategorized first",
            category_raw="Raw A",
        )
    )
    products.upsert(
        SourceProductUpsert(
            shop_id=matching_shop.id,
            source="2gis",
            source_product_id="quality-uncategorized-2",
            title="Uncategorized Second",
            normalized_title="uncategorized second",
            category_raw="Raw A",
        )
    )
    products.upsert(
        SourceProductUpsert(
            shop_id=other_shop.id,
            source="unicom",
            source_product_id="quality-other-source",
            title="Other Source Product",
            normalized_title="other source product",
            category_raw="Raw B",
        )
    )

    response = client.get(
        "/categories/quality",
        params={"source": "2gis", "shop": matching_shop.id, "titles_per_group": 1},
    )

    assert response.status_code == 200
    assert response.json() == {
        "total_products": 3,
        "categorized_products": 1,
        "uncategorized_products": 2,
        "coverage_pct": "33.33",
        "groups": [
            {
                "source": "2gis",
                "shop_id": matching_shop.id,
                "shop_name": "Quality Shop",
                "shop_source_id": "quality-api-shop-1",
                "category_raw": "Raw A",
                "count": 2,
                "titles": ["Uncategorized First"],
            }
        ],
    }
