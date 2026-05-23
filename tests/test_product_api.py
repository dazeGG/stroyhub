from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from stroyhub.core.config import settings
from stroyhub.db import (
    PriceSnapshotCreate,
    PriceSnapshotRepository,
    ShopIdentityCreate,
    ShopIdentityRepository,
    ShopRepository,
    ShopUpsert,
    SourceProductRepository,
    SourceProductUpsert,
)
from stroyhub.models import Category, CategoryOverride

from apps.admin_api.main import create_app
from apps.admin_api.products import get_session


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
    assert payload["total"] == 1
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
    assert payload["total"] == 1


def test_products_endpoint_filters_uncategorized_products(
    client: TestClient, db_session: Session
) -> None:
    shop = ShopRepository(db_session).upsert(
        ShopUpsert(source="2gis", source_id="branch-api-uncategorized", name="Category Shop")
    )
    category = Category(slug="categorized-filter", name="Categorized")
    db_session.add(category)
    db_session.flush()

    uncategorized_product = SourceProductRepository(db_session).upsert(
        SourceProductUpsert(
            shop_id=shop.id,
            source="2gis",
            source_product_id="uncategorized-filter-product",
            title="Uncategorized Filter Product",
            normalized_title="uncategorized filter product",
            category_raw="Raw category",
        )
    )
    SourceProductRepository(db_session).upsert(
        SourceProductUpsert(
            shop_id=shop.id,
            source="2gis",
            source_product_id="categorized-filter-product",
            title="Categorized Filter Product",
            normalized_title="categorized filter product",
            category_id=category.id,
        )
    )

    response = client.get(
        "/products",
        params={"q": "Uncategorized Filter Product", "uncategorized": "true"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert [item["id"] for item in payload["items"]] == [uncategorized_product.id]
    assert payload["items"][0]["category_id"] is None


def test_products_endpoint_filters_parent_category_by_descendants(
    client: TestClient, db_session: Session
) -> None:
    shop = ShopRepository(db_session).upsert(
        ShopUpsert(source="2gis", source_id="branch-api-category-tree", name="Tree Shop")
    )
    root = Category(slug="tree-filter-root", name="Tree Filter Root")
    other_root = Category(slug="tree-filter-other", name="Tree Filter Other")
    db_session.add_all([root, other_root])
    db_session.flush()

    leaf = Category(slug="tree-filter-leaf", name="Tree Filter Leaf", parent_id=root.id)
    db_session.add(leaf)
    db_session.flush()

    grandchild = Category(
        slug="tree-filter-grandchild",
        name="Tree Filter Grandchild",
        parent_id=leaf.id,
    )
    db_session.add(grandchild)
    db_session.flush()

    products = SourceProductRepository(db_session)
    leaf_product = products.upsert(
        SourceProductUpsert(
            shop_id=shop.id,
            source="2gis",
            source_product_id="tree-filter-leaf-product",
            title="Tree Filter Leaf Product",
            normalized_title="tree filter leaf product",
            category_id=leaf.id,
        )
    )
    grandchild_product = products.upsert(
        SourceProductUpsert(
            shop_id=shop.id,
            source="2gis",
            source_product_id="tree-filter-grandchild-product",
            title="Tree Filter Grandchild Product",
            normalized_title="tree filter grandchild product",
            category_id=grandchild.id,
        )
    )
    products.upsert(
        SourceProductUpsert(
            shop_id=shop.id,
            source="2gis",
            source_product_id="tree-filter-other-product",
            title="Tree Filter Other Product",
            normalized_title="tree filter other product",
            category_id=other_root.id,
        )
    )

    response = client.get("/products", params={"category_id": root.id})

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    assert {item["id"] for item in payload["items"]} == {
        grandchild_product.id,
        leaf_product.id,
    }


def test_products_endpoint_filters_leaf_category_by_slug(
    client: TestClient, db_session: Session
) -> None:
    shop = ShopRepository(db_session).upsert(
        ShopUpsert(source="2gis", source_id="branch-api-category-slug", name="Slug Shop")
    )
    root = Category(slug="slug-filter-root", name="Slug Filter Root")
    db_session.add(root)
    db_session.flush()

    leaf = Category(slug="slug-filter-leaf", name="Slug Filter Leaf", parent_id=root.id)
    sibling = Category(
        slug="slug-filter-sibling",
        name="Slug Filter Sibling",
        parent_id=root.id,
    )
    db_session.add_all([leaf, sibling])
    db_session.flush()

    matching_product = SourceProductRepository(db_session).upsert(
        SourceProductUpsert(
            shop_id=shop.id,
            source="2gis",
            source_product_id="slug-filter-leaf-product",
            title="Slug Filter Leaf Product",
            normalized_title="slug filter leaf product",
            category_id=leaf.id,
        )
    )
    SourceProductRepository(db_session).upsert(
        SourceProductUpsert(
            shop_id=shop.id,
            source="2gis",
            source_product_id="slug-filter-sibling-product",
            title="Slug Filter Sibling Product",
            normalized_title="slug filter sibling product",
            category_id=sibling.id,
        )
    )

    response = client.get("/products", params={"category_slug": "slug-filter-leaf"})

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [matching_product.id]


@pytest.mark.parametrize(
    ("sort", "expected_keys"),
    [
        ("latest_price", ["cheap", "expensive", "unpriced"]),
        ("-latest_price", ["expensive", "cheap", "unpriced"]),
        ("title", ["alpha", "bravo", "charlie"]),
        ("-title", ["charlie", "bravo", "alpha"]),
        ("shop", ["alpha", "charlie", "bravo"]),
        ("-shop", ["bravo", "charlie", "alpha"]),
        ("last_seen_at", ["bravo", "alpha", "charlie"]),
        ("-last_seen_at", ["charlie", "alpha", "bravo"]),
    ],
)
def test_products_endpoint_supports_sort_modes(
    client: TestClient,
    db_session: Session,
    sort: str,
    expected_keys: list[str],
) -> None:
    alpha_shop = ShopRepository(db_session).upsert(
        ShopUpsert(source="2gis", source_id="sort-shop-alpha", name="Alpha Shop")
    )
    beta_shop = ShopRepository(db_session).upsert(
        ShopUpsert(source="2gis", source_id="sort-shop-beta", name="Beta Shop")
    )
    gamma_shop = ShopRepository(db_session).upsert(
        ShopUpsert(source="2gis", source_id="sort-shop-gamma", name="Gamma Shop")
    )
    products = SourceProductRepository(db_session)
    alpha = products.upsert(
        SourceProductUpsert(
            shop_id=alpha_shop.id,
            source="2gis",
            source_product_id="sort-product-alpha",
            title="Sort Mode Alpha",
            normalized_title="sort mode alpha",
            observed_at=datetime(2026, 5, 17, 9, 0, tzinfo=UTC),
        )
    )
    bravo = products.upsert(
        SourceProductUpsert(
            shop_id=gamma_shop.id,
            source="2gis",
            source_product_id="sort-product-bravo",
            title="Sort Mode Bravo",
            normalized_title="sort mode bravo",
            observed_at=datetime(2026, 5, 17, 8, 0, tzinfo=UTC),
        )
    )
    charlie = products.upsert(
        SourceProductUpsert(
            shop_id=beta_shop.id,
            source="2gis",
            source_product_id="sort-product-charlie",
            title="Sort Mode Charlie",
            normalized_title="sort mode charlie",
            observed_at=datetime(2026, 5, 17, 10, 0, tzinfo=UTC),
        )
    )
    prices = PriceSnapshotRepository(db_session)
    prices.add(
        PriceSnapshotCreate(
            source_product_id=alpha.id,
            price=Decimal("10.00"),
            parsed_at=datetime(2026, 5, 17, 9, 5, tzinfo=UTC),
        )
    )
    prices.add(
        PriceSnapshotCreate(
            source_product_id=charlie.id,
            price=Decimal("20.00"),
            parsed_at=datetime(2026, 5, 17, 10, 5, tzinfo=UTC),
        )
    )

    response = client.get("/products", params={"q": "sort mode", "sort": sort})

    assert response.status_code == 200
    key_by_id = {
        alpha.id: "alpha",
        bravo.id: "bravo",
        charlie.id: "charlie",
    }
    price_key_by_id = {
        alpha.id: "cheap",
        bravo.id: "unpriced",
        charlie.id: "expensive",
    }
    key_map = price_key_by_id if "price" in sort else key_by_id
    assert [key_map[item["id"]] for item in response.json()["items"]] == expected_keys


def test_products_endpoint_rejects_invalid_sort(client: TestClient) -> None:
    response = client.get("/products", params={"sort": "not-a-sort"})

    assert response.status_code == 422


def test_products_endpoint_handles_empty_results(client: TestClient) -> None:
    response = client.get("/products", params={"q": "nothing-here"})

    assert response.status_code == 200
    assert response.json() == {"items": [], "limit": 50, "offset": 0, "total": 0}


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
    non_matching_product = SourceProductRepository(db_session).upsert(
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
    returned_ids = {item["id"] for item in response.json()["items"]}
    assert matching_product.id in returned_ids
    assert non_matching_product.id not in returned_ids


def test_product_detail_endpoint_returns_source_product(
    client: TestClient, db_session: Session
) -> None:
    shop = ShopRepository(db_session).upsert(
        ShopUpsert(source="2gis", source_id="branch-api-detail", name="Detail Shop")
    )
    product = SourceProductRepository(db_session).upsert(
        SourceProductUpsert(
            shop_id=shop.id,
            source="2gis",
            source_product_id="detail-api-1",
            title="Detail Cement M400",
            normalized_title="detail cement m400",
            category_raw="Catalog / Cement",
            unit_raw="bag",
            observed_at=datetime(2026, 5, 18, 8, 0, tzinfo=UTC),
        )
    )
    PriceSnapshotRepository(db_session).add(
        PriceSnapshotCreate(
            source_product_id=product.id,
            price=Decimal("560.00"),
            unit_raw="bag",
            parsed_at=datetime(2026, 5, 18, 8, 5, tzinfo=UTC),
        )
    )

    response = client.get(f"/products/{product.id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == product.id
    assert payload["title"] == "Detail Cement M400"
    assert payload["shop"]["name"] == "Detail Shop"
    assert payload["latest_price"]["price"] == "560.00"
    assert payload["latest_price"]["unit_raw"] == "bag"
    assert payload["category_override"] is None


def test_product_detail_endpoint_returns_404_for_missing_product(
    client: TestClient,
) -> None:
    response = client.get("/products/999999999")

    assert response.status_code == 404
    assert response.json() == {
        "code": "source_product_not_found",
        "message": "Source product not found",
        "details": {},
    }


def test_product_category_override_endpoint_creates_reads_and_reverts_override(
    client: TestClient, db_session: Session
) -> None:
    shop = ShopRepository(db_session).upsert(
        ShopUpsert(source="2gis", source_id="branch-api-override", name="Override Shop")
    )
    root = Category(slug="api-override-root", name="Override Root")
    db_session.add(root)
    db_session.flush()
    original_category = Category(
        slug="api-override-original",
        name="Override Original",
        parent_id=root.id,
    )
    manual_category = Category(
        slug="api-override-manual",
        name="Override Manual",
        parent_id=root.id,
    )
    db_session.add_all([original_category, manual_category])
    db_session.flush()
    product = SourceProductRepository(db_session).upsert(
        SourceProductUpsert(
            shop_id=shop.id,
            source="2gis",
            source_product_id="override-api-1",
            title="Override Product",
            normalized_title="override product",
            category_id=original_category.id,
        )
    )

    assign_response = client.put(
        f"/products/{product.id}/category-override",
        json={
            "category_id": manual_category.id,
            "reason": "admin review",
            "actor": "tester",
        },
    )

    assert assign_response.status_code == 200
    assigned = assign_response.json()
    assert assigned["category_id"] == manual_category.id
    assert assigned["category_override"]["category_id"] == manual_category.id
    assert assigned["category_override"]["previous_category_id"] == original_category.id
    assert assigned["category_override"]["reason"] == "admin review"
    assert assigned["category_override"]["created_by"] == "tester"

    detail_response = client.get(f"/products/{product.id}")

    assert detail_response.status_code == 200
    assert detail_response.json()["category_override"]["category_id"] == manual_category.id

    revert_response = client.delete(
        f"/products/{product.id}/category-override",
        params={"actor": "tester"},
    )

    assert revert_response.status_code == 200
    reverted = revert_response.json()
    assert reverted["category_id"] == original_category.id
    assert reverted["category_override"] is None


def test_product_category_override_endpoint_rejects_root_category(
    client: TestClient, db_session: Session
) -> None:
    shop = ShopRepository(db_session).upsert(
        ShopUpsert(source="2gis", source_id="branch-api-root-override", name="Root Shop")
    )
    root = Category(slug="api-root-override-root", name="Root Override Root")
    db_session.add(root)
    db_session.flush()
    child = Category(
        slug="api-root-override-child",
        name="Root Override Child",
        parent_id=root.id,
    )
    db_session.add(child)
    db_session.flush()
    product = SourceProductRepository(db_session).upsert(
        SourceProductUpsert(
            shop_id=shop.id,
            source="2gis",
            source_product_id="root-override-api-1",
            title="Root Override Product",
            normalized_title="root override product",
            category_id=child.id,
        )
    )

    response = client.put(
        f"/products/{product.id}/category-override",
        json={"category_id": root.id},
    )

    assert response.status_code == 422
    assert response.json() == {
        "code": "category_override_requires_leaf",
        "message": "Category override must target a leaf category",
        "details": {},
    }


def test_product_category_override_revert_returns_404_without_active_override(
    client: TestClient, db_session: Session
) -> None:
    shop = ShopRepository(db_session).upsert(
        ShopUpsert(source="2gis", source_id="branch-api-no-override", name="No Override Shop")
    )
    product = SourceProductRepository(db_session).upsert(
        SourceProductUpsert(
            shop_id=shop.id,
            source="2gis",
            source_product_id="no-override-api-1",
            title="No Override Product",
            normalized_title="no override product",
        )
    )

    response = client.delete(f"/products/{product.id}/category-override")

    assert response.status_code == 404
    assert response.json() == {
        "code": "active_category_override_not_found",
        "message": "Active category override not found",
        "details": {},
    }


def test_product_category_override_put_is_idempotent_for_same_payload(
    client: TestClient, db_session: Session
) -> None:
    shop = ShopRepository(db_session).upsert(
        ShopUpsert(
            source="2gis",
            source_id="branch-api-idempotent-override",
            name="Idempotent Shop",
        )
    )
    root = Category(slug="api-idempotent-override-root", name="Idempotent Override Root")
    db_session.add(root)
    db_session.flush()
    original = Category(
        slug="api-idempotent-override-original",
        name="Idempotent Override Original",
        parent_id=root.id,
    )
    manual = Category(
        slug="api-idempotent-override-manual",
        name="Idempotent Override Manual",
        parent_id=root.id,
    )
    db_session.add_all([original, manual])
    db_session.flush()
    product = SourceProductRepository(db_session).upsert(
        SourceProductUpsert(
            shop_id=shop.id,
            source="2gis",
            source_product_id="idempotent-override-api-1",
            title="Idempotent Override Product",
            normalized_title="idempotent override product",
            category_id=original.id,
        )
    )

    first = client.put(
        f"/products/{product.id}/category-override",
        json={"category_id": manual.id, "reason": "same", "actor": "admin"},
    )
    second = client.put(
        f"/products/{product.id}/category-override",
        json={"category_id": manual.id, "reason": "  same  ", "actor": "  admin  "},
    )
    total = db_session.scalar(
        select(func.count())
        .select_from(CategoryOverride)
        .where(CategoryOverride.source_product_id == product.id)
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["category_override"]["id"] == second.json()["category_override"]["id"]
    assert total == 1


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
    assert response.json() == {
        "code": "source_product_not_found",
        "message": "Source product not found",
        "details": {},
    }


def test_public_products_prefer_healthy_identity_preferred_source(
    client: TestClient,
    db_session: Session,
) -> None:
    identity = ShopIdentityRepository(db_session).create(
        ShopIdentityCreate(display_name="Preferred Shop", preferred_source="unicom")
    )
    fallback_shop = ShopRepository(db_session).upsert(
        ShopUpsert(
            source="2gis",
            source_id="public-priority-fallback",
            name="Fallback Shop",
            shop_identity_id=identity.id,
            scrape_status="success",
        )
    )
    preferred_shop = ShopRepository(db_session).upsert(
        ShopUpsert(
            source="unicom",
            source_id="public-priority-preferred",
            name="Preferred Shop",
            shop_identity_id=identity.id,
            scrape_status="success",
        )
    )
    fallback_product = SourceProductRepository(db_session).upsert(
        SourceProductUpsert(
            shop_id=fallback_shop.id,
            source="2gis",
            source_product_id="public-priority-fallback-product",
            title="Priority Cement M500",
            normalized_title="priority cement m500",
        )
    )
    preferred_product = SourceProductRepository(db_session).upsert(
        SourceProductUpsert(
            shop_id=preferred_shop.id,
            source="unicom",
            source_product_id="public-priority-preferred-product",
            title="Priority Cement M500",
            normalized_title="priority cement m500",
        )
    )

    response = client.get("/products", params={"q": "Priority Cement M500"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert [item["id"] for item in payload["items"]] == [preferred_product.id]
    assert payload["items"][0]["shop"]["source"] == "unicom"

    assert client.get(f"/products/{fallback_product.id}").status_code == 404
    assert client.get(f"/products/{fallback_product.id}/prices").status_code == 404


def test_public_products_fall_back_when_preferred_source_is_unhealthy(
    client: TestClient,
    db_session: Session,
) -> None:
    identity = ShopIdentityRepository(db_session).create(
        ShopIdentityCreate(display_name="Fallback Identity", preferred_source="unicom")
    )
    fallback_shop = ShopRepository(db_session).upsert(
        ShopUpsert(
            source="2gis",
            source_id="public-fallback-visible",
            name="Fallback Visible Shop",
            shop_identity_id=identity.id,
            scrape_status="success",
        )
    )
    preferred_shop = ShopRepository(db_session).upsert(
        ShopUpsert(
            source="unicom",
            source_id="public-fallback-hidden",
            name="Preferred Hidden Shop",
            shop_identity_id=identity.id,
            scrape_status="disabled",
        )
    )
    visible_product = SourceProductRepository(db_session).upsert(
        SourceProductUpsert(
            shop_id=fallback_shop.id,
            source="2gis",
            source_product_id="public-fallback-visible-product",
            title="Fallback Cement M400",
            normalized_title="fallback cement m400",
        )
    )
    SourceProductRepository(db_session).upsert(
        SourceProductUpsert(
            shop_id=preferred_shop.id,
            source="unicom",
            source_product_id="public-fallback-hidden-product",
            title="Fallback Cement M400",
            normalized_title="fallback cement m400",
        )
    )

    response = client.get("/products", params={"q": "Fallback Cement M400"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert [item["id"] for item in payload["items"]] == [visible_product.id]
    assert payload["items"][0]["shop"]["source"] == "2gis"


@pytest.mark.parametrize("identity_status", ["hold", "disabled", "out_of_scope"])
def test_public_products_hide_non_active_shop_identity_statuses(
    client: TestClient,
    db_session: Session,
    identity_status: str,
) -> None:
    identity = ShopIdentityRepository(db_session).create(
        ShopIdentityCreate(display_name=f"Hidden {identity_status}", status=identity_status)
    )
    shop = ShopRepository(db_session).upsert(
        ShopUpsert(
            source="2gis",
            source_id=f"public-hidden-{identity_status}",
            name="Hidden Shop",
            shop_identity_id=identity.id,
            scrape_status="success",
        )
    )
    product = SourceProductRepository(db_session).upsert(
        SourceProductUpsert(
            shop_id=shop.id,
            source="2gis",
            source_product_id=f"public-hidden-{identity_status}-product",
            title=f"Hidden Product {identity_status}",
            normalized_title=f"hidden product {identity_status}",
        )
    )

    response = client.get("/products", params={"q": f"Hidden Product {identity_status}"})

    assert response.status_code == 200
    assert response.json()["total"] == 0
    assert client.get(f"/products/{product.id}").status_code == 404
