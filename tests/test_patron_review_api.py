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
from stroyhub.models import SourceProduct

from apps.admin_api.main import create_app
from apps.admin_api.patron_review import get_session


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


def test_patron_review_returns_next_item_and_records_not_product_decision(
    client: TestClient,
    db_session: Session,
) -> None:
    baseline = _stats(client)
    product = _patron_review_product(db_session, source_id="patron-review-not-product")

    response = client.get("/patron-review")

    assert response.status_code == 200
    payload = response.json()
    assert payload["stats"] == _stats_delta(baseline, total=1, remaining=1)
    assert payload["item"]["id"] == product.id
    assert payload["item"]["latest_price"]["price"] == "1200.00"
    assert payload["item"]["catalog_eligibility"]["method"] == "patron"

    decision_response = client.post(
        f"/patron-review/{product.id}/decision",
        json={
            "action": "not_product",
            "actor": "reviewer",
            "reason": "broad 2GIS listing",
        },
    )

    assert decision_response.status_code == 200
    assert decision_response.json()["stats"] == _stats_delta(baseline, total=1, reviewed=1)

    db_session.refresh(product)
    assert product.is_not_product is True
    assert product.raw["operator_review"]["patron_review"]["status"] == "not_product"
    assert product.raw["catalog_eligibility"]["method"] == "operator_review"


def test_patron_review_can_review_patron_rejected_products_by_probability(
    client: TestClient,
    db_session: Session,
) -> None:
    params = {"mode": "patron_rejected", "min_probability": "0.999"}
    baseline = _stats(client, params=params)
    _patron_rejected_product(
        db_session,
        source_id="patron-rejected-low-probability",
        probability="0.998",
    )
    high_probability = _patron_rejected_product(
        db_session,
        source_id="patron-rejected-high-probability",
        probability="0.999",
    )

    response = client.get("/patron-review", params=params)

    assert response.status_code == 200
    payload = response.json()
    assert payload["stats"] == _stats_delta(baseline, total=1, remaining=1)
    assert payload["item"]["id"] == high_probability.id
    assert payload["item"]["catalog_eligibility"]["not_product_probability"] == "0.999"


def test_patron_review_records_patron_rejected_queue_decision(
    client: TestClient,
    db_session: Session,
) -> None:
    params = {"mode": "patron_rejected", "min_probability": "0.900"}
    high_threshold_params = {"mode": "patron_rejected", "min_probability": "0.990"}
    baseline = _stats(client, params=params)
    high_threshold_baseline = _stats(client, params=high_threshold_params)
    product = _patron_rejected_product(
        db_session,
        source_id="patron-rejected-review-product",
        probability="0.910",
    )

    response = client.post(
        f"/patron-review/{product.id}/decision",
        params=params,
        json={
            "action": "product",
            "actor": "reviewer",
            "reason": "specific product card",
        },
    )

    assert response.status_code == 200
    assert response.json()["stats"] == _stats_delta(baseline, total=1, reviewed=1)
    assert _stats(client, params=high_threshold_params) == high_threshold_baseline
    db_session.refresh(product)
    assert product.is_not_product is False
    assert product.raw["operator_review"]["patron_review"]["queue"] == "patron_rejected"
    assert product.raw["operator_review"]["patron_review"]["status"] == "product"
    assert (
        product.raw["operator_review"]["patron_review"]["catalog_eligibility"][
            "not_product_probability"
        ]
        == "0.910"
    )
    assert product.raw["catalog_eligibility"]["status"] == "eligible"
    assert product.raw["catalog_eligibility"]["method"] == "operator_review"


def test_patron_review_undo_restores_previous_product_state(
    client: TestClient,
    db_session: Session,
) -> None:
    baseline = _stats(client)
    product = _patron_review_product(db_session, source_id="patron-review-undo")

    assert client.post(
        f"/patron-review/{product.id}/decision",
        json={"action": "product", "actor": "reviewer"},
    ).status_code == 200

    undo_response = client.post(
        "/patron-review/undo",
        json={"actor": "reviewer", "reason": "misclick"},
    )

    assert undo_response.status_code == 200
    assert undo_response.json()["stats"] == _stats_delta(baseline, total=1, remaining=1)
    db_session.refresh(product)
    assert product.is_not_product is False
    assert "operator_review" not in product.raw
    assert product.raw["catalog_eligibility"]["status"] == "needs_review"


def test_patron_review_undo_walks_back_multiple_review_decisions(
    client: TestClient,
    db_session: Session,
) -> None:
    baseline = _stats(client)
    first_product = _patron_review_product(db_session, source_id="patron-review-undo-first")
    second_product = _patron_review_product(db_session, source_id="patron-review-undo-second")

    assert client.post(
        f"/patron-review/{first_product.id}/decision",
        json={"action": "product", "actor": "reviewer"},
    ).status_code == 200
    assert client.post(
        f"/patron-review/{second_product.id}/decision",
        json={"action": "not_product", "actor": "reviewer"},
    ).status_code == 200

    first_undo = client.post("/patron-review/undo", json={"actor": "reviewer"})
    second_undo = client.post("/patron-review/undo", json={"actor": "reviewer"})

    assert first_undo.status_code == 200
    assert first_undo.json()["product_id"] == second_product.id
    assert first_undo.json()["stats"] == _stats_delta(
        baseline,
        total=2,
        remaining=1,
        reviewed=1,
    )
    assert second_undo.status_code == 200
    assert second_undo.json()["product_id"] == first_product.id
    assert second_undo.json()["stats"] == _stats_delta(baseline, total=2, remaining=2)


def _patron_review_product(session: Session, *, source_id: str) -> SourceProduct:
    shop = ShopRepository(session).upsert(
        ShopUpsert(source="2gis", source_id=f"shop-{source_id}", name="Patron Shop")
    )
    product = SourceProductRepository(session).upsert(
        SourceProductUpsert(
            shop_id=shop.id,
            source="2gis",
            source_product_id=source_id,
            title="Брус от 1200 рублей",
            normalized_title="брус от 1200 рублей",
            category_raw="Пиломатериалы",
            raw={
                "catalog_eligibility": {
                    "status": "needs_review",
                    "method": "patron",
                    "score": 52,
                    "reasons": ["patron_uncertain"],
                    "not_product_probability": "0.480",
                }
            },
            observed_at=datetime(2030, 5, 27, 12, 0, tzinfo=UTC),
            is_not_product=False,
        )
    )
    PriceSnapshotRepository(session).add(
        PriceSnapshotCreate(
            source_product_id=product.id,
            price=Decimal("1200.00"),
            price_kind="from",
            parsed_at=datetime(2030, 5, 27, 12, 1, tzinfo=UTC),
        )
    )
    return product


def _patron_rejected_product(
    session: Session,
    *,
    source_id: str,
    probability: str,
) -> SourceProduct:
    shop = ShopRepository(session).upsert(
        ShopUpsert(source="2gis", source_id=f"shop-{source_id}", name="Patron Shop")
    )
    product = SourceProductRepository(session).upsert(
        SourceProductUpsert(
            shop_id=shop.id,
            source="2gis",
            source_product_id=source_id,
            title="Цемент М500 25 кг",
            normalized_title="цемент м500 25 кг",
            category_raw="Цемент",
            raw={
                "catalog_eligibility": {
                    "status": "ineligible",
                    "method": "patron",
                    "score": 8,
                    "reasons": ["patron_not_product"],
                    "not_product_probability": probability,
                }
            },
            observed_at=datetime(2030, 5, 27, 13, 0, tzinfo=UTC),
            is_not_product=True,
        )
    )
    PriceSnapshotRepository(session).add(
        PriceSnapshotCreate(
            source_product_id=product.id,
            price=Decimal("550.00"),
            price_kind="exact",
            parsed_at=datetime(2030, 5, 27, 13, 1, tzinfo=UTC),
        )
    )
    return product


def _stats(client: TestClient, *, params: dict[str, str] | None = None) -> dict[str, int]:
    response = client.get("/patron-review", params=params)
    assert response.status_code == 200
    return response.json()["stats"]


def _stats_delta(
    baseline: dict[str, int],
    *,
    total: int = 0,
    remaining: int = 0,
    reviewed: int = 0,
    skipped: int = 0,
) -> dict[str, int]:
    return {
        "total": baseline["total"] + total,
        "remaining": baseline["remaining"] + remaining,
        "reviewed": baseline["reviewed"] + reviewed,
        "skipped": baseline["skipped"] + skipped,
    }
