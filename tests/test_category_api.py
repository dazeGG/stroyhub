from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from stroyhub.catalog.categories import CategoryTreeItem
from stroyhub.core.config import settings
from stroyhub.db import ShopRepository, ShopUpsert, SourceProductRepository, SourceProductUpsert
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
