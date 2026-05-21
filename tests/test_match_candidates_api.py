from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from stroyhub.core.config import settings
from stroyhub.db import ShopRepository, ShopUpsert, SourceProductRepository, SourceProductUpsert
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


def test_match_candidates_endpoint_returns_readonly_candidate_pairs(
    client: TestClient,
    db_session: Session,
) -> None:
    category = Category(slug="match-api-category", name="Match API Category")
    db_session.add(category)
    db_session.flush()

    first_shop = ShopRepository(db_session).upsert(
        ShopUpsert(source="2gis", source_id="match-api-shop-1", name="First Match Shop")
    )
    second_shop = ShopRepository(db_session).upsert(
        ShopUpsert(source="2gis", source_id="match-api-shop-2", name="Second Match Shop")
    )
    other_shop = ShopRepository(db_session).upsert(
        ShopUpsert(source="unicom", source_id="match-api-shop-3", name="Other Match Shop")
    )
    products = SourceProductRepository(db_session)
    left = products.upsert(
        SourceProductUpsert(
            shop_id=first_shop.id,
            source="2gis",
            source_product_id="match-api-left",
            title="Цемент М500 50кг",
            normalized_title="цемент м500 50кг",
            category_id=category.id,
            category_raw="Цемент",
        )
    )
    right = products.upsert(
        SourceProductUpsert(
            shop_id=second_shop.id,
            source="2gis",
            source_product_id="match-api-right",
            title="Цемент М500 50кг",
            normalized_title="цемент м500 50кг",
            category_id=category.id,
            category_raw="Цемент",
        )
    )
    products.upsert(
        SourceProductUpsert(
            shop_id=other_shop.id,
            source="unicom",
            source_product_id="match-api-other",
            title="Краска белая 10л",
            normalized_title="краска белая 10л",
            category_id=category.id,
            category_raw="Краски",
        )
    )

    response = client.get(
        "/matches/candidates",
        params={"source": "2gis", "category_id": category.id, "min_confidence": 0.9},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["products_considered"] == 2
    assert payload["candidates"] == [
        {
            "left": {
                "id": left.id,
                "source": "2gis",
                "shop_id": first_shop.id,
                "shop_name": "First Match Shop",
                "shop_source_id": "match-api-shop-1",
                "title": "Цемент М500 50кг",
                "normalized_title": "цемент м500 50кг",
                "category_id": category.id,
                "category_raw": "Цемент",
            },
            "right": {
                "id": right.id,
                "source": "2gis",
                "shop_id": second_shop.id,
                "shop_name": "Second Match Shop",
                "shop_source_id": "match-api-shop-2",
                "title": "Цемент М500 50кг",
                "normalized_title": "цемент м500 50кг",
                "category_id": category.id,
                "category_raw": "Цемент",
            },
            "confidence": 1.0,
            "reason": {
                "method": "exact_normalized_title",
                "exact_title": True,
                "matched_normalized_title": "цемент м500 50кг",
                "token_overlap": ["50кг", "м500", "цемент"],
                "left_only_tokens": [],
                "right_only_tokens": [],
                "ignored_tokens": [],
                "blocked_by": [],
                "token_similarity": 1.0,
                "same_category": True,
            },
        }
    ]
