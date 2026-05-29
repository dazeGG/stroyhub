from collections.abc import Iterator
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from stroyhub.core.config import settings
from stroyhub.db import (
    CanonicalProductCreate,
    CanonicalProductRepository,
    PriceSnapshotCreate,
    PriceSnapshotRepository,
    ProductMatchCreate,
    ProductMatchRepository,
    ShopRepository,
    ShopUpsert,
    SourceProductRepository,
    SourceProductUpsert,
)
from stroyhub.models import Category

from apps.admin_api.canonical_products import get_session
from apps.admin_api.main import create_app


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


def test_canonical_products_endpoint_creates_lists_and_filters(
    client: TestClient,
    db_session: Session,
) -> None:
    parent = Category(slug="canonical-parent", name="Canonical Parent")
    db_session.add(parent)
    db_session.flush()
    category = Category(
        slug="canonical-cement",
        name="Canonical Cement",
        parent_id=parent.id,
    )
    other_category = Category(slug="canonical-other", name="Canonical Other")
    db_session.add_all([category, other_category])
    db_session.flush()

    response = client.post(
        "/canonical-products",
        json={
            "title": "Canonical Unique Cement M500 50kg",
            "category_id": category.id,
            "brand": "Test Brand",
            "unit_raw": "50kg",
            "attributes": {"weight": {"value": "50", "unit": "kg"}},
        },
    )

    assert response.status_code == 201
    created = response.json()
    assert created["title"] == "Canonical Unique Cement M500 50kg"
    assert created["normalized_title"] == "canonical unique cement m500 50kg"
    assert created["category"]["slug"] == "canonical-cement"
    assert created["match_counts"] == {"accepted": 0, "candidate": 0, "rejected": 0}
    assert created["accepted_source_products"] == []

    CanonicalProductRepository(db_session).create(
        CanonicalProductCreate(
            title="Other Canonical Product",
            normalized_title="other canonical product",
            category_id=other_category.id,
            match_status="inactive",
        )
    )

    list_response = client.get(
        "/canonical-products",
        params={
            "q": "Unique Cement",
            "category_id": parent.id,
            "match_status": "active",
        },
    )

    assert list_response.status_code == 200
    payload = list_response.json()
    assert payload["total"] == 1
    assert [item["id"] for item in payload["items"]] == [created["id"]]


def test_canonical_product_from_source_seed_preserves_source_product(
    client: TestClient,
    db_session: Session,
) -> None:
    category = Category(slug="canonical-seed", name="Canonical Seed")
    db_session.add(category)
    db_session.flush()
    shop = ShopRepository(db_session).upsert(
        ShopUpsert(source="2gis", source_id="canonical-seed-shop", name="Seed Shop")
    )
    source_product = SourceProductRepository(db_session).upsert(
        SourceProductUpsert(
            shop_id=shop.id,
            source="2gis",
            source_product_id="canonical-seed-product",
            title="Seed Cement M400 25kg",
            normalized_title="seed cement m400 25kg",
            category_id=category.id,
            unit_raw="25kg",
        )
    )

    response = client.post(f"/canonical-products/from-source/{source_product.id}", json={})

    assert response.status_code == 201
    payload = response.json()
    db_session.expire(source_product)
    assert payload["title"] == "Seed Cement M400 25kg"
    assert payload["category_id"] == category.id
    assert payload["unit_raw"] == "25kg"
    assert source_product.title == "Seed Cement M400 25kg"
    assert source_product.product_matches == []


def test_canonical_product_detail_and_update_show_linked_source_products(
    client: TestClient,
    db_session: Session,
) -> None:
    category = Category(slug="canonical-detail", name="Canonical Detail")
    db_session.add(category)
    db_session.flush()
    canonical = CanonicalProductRepository(db_session).create(
        CanonicalProductCreate(
            title="Detail Cement",
            normalized_title="detail cement",
            category_id=category.id,
        )
    )
    shop = ShopRepository(db_session).upsert(
        ShopUpsert(source="2gis", source_id="canonical-detail-shop", name="Detail Shop")
    )
    accepted_source = SourceProductRepository(db_session).upsert(
        SourceProductUpsert(
            shop_id=shop.id,
            source="2gis",
            source_product_id="canonical-detail-accepted",
            title="Detail Cement Source",
            normalized_title="detail cement source",
            category_id=category.id,
            unit_raw="bag",
            image_url="https://example.test/detail.jpg",
            raw={"product_url": "https://example.test/source-product"},
        )
    )
    ineligible_source = SourceProductRepository(db_session).upsert(
        SourceProductUpsert(
            shop_id=shop.id,
            source="2gis",
            source_product_id="canonical-detail-ineligible",
            title="Detail Cement Ineligible",
            normalized_title="detail cement ineligible",
            category_id=category.id,
            raw={"catalog_eligibility": {"status": "ineligible"}},
            is_not_product=True,
        )
    )
    candidate_source = SourceProductRepository(db_session).upsert(
        SourceProductUpsert(
            shop_id=shop.id,
            source="2gis",
            source_product_id="canonical-detail-candidate",
            title="Detail Cement Candidate",
            normalized_title="detail cement candidate",
            category_id=category.id,
        )
    )
    matches = ProductMatchRepository(db_session)
    PriceSnapshotRepository(db_session).add(
        PriceSnapshotCreate(
            source_product_id=accepted_source.id,
            price=Decimal("777.00"),
        )
    )
    accepted_match = matches.create(
        ProductMatchCreate(
            canonical_product_id=canonical.id,
            source_product_id=accepted_source.id,
            confidence=Decimal("1.000"),
            method="manual",
            status="accepted",
        )
    )
    matches.create(
        ProductMatchCreate(
            canonical_product_id=canonical.id,
            source_product_id=ineligible_source.id,
            confidence=Decimal("1.000"),
            method="manual",
            status="accepted",
        )
    )
    candidate_match = matches.create(
        ProductMatchCreate(
            canonical_product_id=canonical.id,
            source_product_id=candidate_source.id,
            confidence=Decimal("0.850"),
            method="token_similarity",
            status="candidate",
        )
    )
    rejected_source = SourceProductRepository(db_session).upsert(
        SourceProductUpsert(
            shop_id=shop.id,
            source="2gis",
            source_product_id="canonical-detail-rejected",
            title="Detail Cement Rejected",
            normalized_title="detail cement rejected",
            category_id=category.id,
        )
    )
    rejected_match = matches.create(
        ProductMatchCreate(
            canonical_product_id=canonical.id,
            source_product_id=rejected_source.id,
            confidence=Decimal("0.750"),
            method="token_similarity",
            status="rejected",
        )
    )

    update_response = client.patch(
        f"/canonical-products/{canonical.id}",
        json={"title": "Detail Cement Updated", "match_status": "inactive"},
    )

    assert update_response.status_code == 200
    payload = update_response.json()
    assert payload["title"] == "Detail Cement Updated"
    assert payload["normalized_title"] == "detail cement updated"
    assert payload["match_status"] == "inactive"
    assert payload["match_counts"] == {"accepted": 2, "candidate": 1, "rejected": 1}
    assert payload["accepted_source_products"] == [
        {
            "id": accepted_source.id,
            "match_id": accepted_match.id,
            "source": "2gis",
            "source_product_id": "canonical-detail-accepted",
            "title": "Detail Cement Source",
            "normalized_title": "detail cement source",
            "shop_id": shop.id,
            "shop_name": "Detail Shop",
            "shop_source_id": "canonical-detail-shop",
            "category_raw": None,
            "unit_raw": "bag",
            "source_url": "https://example.test/source-product",
            "image_url": "https://example.test/detail.jpg",
            "last_seen_at": accepted_source.last_seen_at.isoformat().replace("+00:00", "Z"),
            "latest_price": {
                "price": "777.00",
                "price_kind": "exact",
                "price_text": "777.00 RUB",
                "currency": "RUB",
                "unit_raw": None,
                "source_updated_at": None,
                "parsed_at": payload["accepted_source_products"][0]["latest_price"]["parsed_at"],
            },
            "confidence": "1.000",
        }
    ]
    assert payload["accepted_offer_groups"][0]["shop_id"] == shop.id
    assert payload["accepted_offer_groups"][0]["source"] == "2gis"
    assert [item["id"] for item in payload["accepted_offer_groups"][0]["items"]] == [
        accepted_source.id
    ]
    assert payload["candidate_source_products"][0]["id"] == candidate_source.id
    assert payload["candidate_source_products"][0]["match_id"] == candidate_match.id
    assert payload["rejected_source_products"][0]["id"] == rejected_source.id
    assert payload["rejected_source_products"][0]["match_id"] == rejected_match.id


def test_canonical_product_validation_rejects_invalid_status_and_blank_title(
    client: TestClient,
) -> None:
    invalid_status = client.post(
        "/canonical-products",
        json={"title": "Valid title", "match_status": "unknown"},
    )
    blank_title = client.post(
        "/canonical-products",
        json={"title": "   ", "match_status": "active"},
    )

    assert invalid_status.status_code == 422
    assert blank_title.status_code == 422
