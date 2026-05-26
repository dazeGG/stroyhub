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
    ProductMatchCreate,
    ProductMatchRepository,
    ShopRepository,
    ShopUpsert,
    SourceProductRepository,
    SourceProductUpsert,
)
from stroyhub.models import CanonicalProduct, Category, SourceProduct

from apps.admin_api.main import create_app
from apps.admin_api.operator_decisions import get_session


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


def test_operator_decisions_record_and_export_normalization_actions(
    client: TestClient,
    db_session: Session,
) -> None:
    canonical = _canonical(db_session, title="Operator Decision Cement")
    source_product = _source_product(
        db_session,
        source_id="operator-decision-source",
        category_id=canonical.category_id,
    )
    decision_context = {
        "engine": "normalization_decision_v1",
        "action": "attach_to_existing",
        "status": "ready_to_accept",
        "confidence": "0.982",
        "method": "attribute_rules",
        "positive_evidence": [{"kind": "category", "result": "pass"}],
        "negative_evidence": [],
        "blockers": [],
        "alternatives": [
            {
                "canonical_product_id": canonical.id,
                "canonical_title": canonical.title,
                "confidence": "0.982",
            }
        ],
    }
    ProductMatchRepository(db_session).create(
        ProductMatchCreate(
            canonical_product_id=canonical.id,
            source_product_id=source_product.id,
            confidence=Decimal("0.982"),
            method="attribute_rules",
            status="candidate",
            reason={"decision": decision_context},
        )
    )

    accept_response = client.post(
        "/product-matches/accept",
        json={
            "canonical_product_id": canonical.id,
            "source_product_id": source_product.id,
            "actor": "reviewer",
            "reason": "same material",
        },
    )
    list_response = client.get(
        "/operator-decisions",
        params={"decision_type": "normalization", "source_product_id": source_product.id},
    )
    export_response = client.get(
        "/operator-decisions/export",
        params={"decision_type": "normalization", "source_product_id": source_product.id},
    )
    dataset_response = client.get("/operator-decisions/datasets/normalization")

    assert accept_response.status_code == 200
    assert list_response.status_code == 200
    payload = list_response.json()
    assert payload["total"] == 1
    item = payload["items"][0]
    assert item["decision_type"] == "normalization"
    assert item["action"] == "attach_to_existing"
    assert item["actor"] == "reviewer"
    assert item["canonical_product_id"] == canonical.id
    assert item["evidence"]["positive_evidence"] == [{"kind": "category", "result": "pass"}]
    assert item["alternatives"]["items"][0]["canonical_product_id"] == canonical.id
    assert item["previous_state"]["match"]["status"] == "candidate"
    assert item["new_state"]["status"] == "accepted"

    assert export_response.status_code == 200
    assert '"decision_type": "normalization"' in export_response.text
    assert '"action": "attach_to_existing"' in export_response.text

    assert dataset_response.status_code == 200
    dataset_items = dataset_response.json()["items"]
    assert any(
        example["source_product_id"] == source_product.id
        and example["canonical_product_id"] == canonical.id
        and example["outcome"] == "accepted"
        for example in dataset_items
    )


def test_operator_decisions_record_category_and_data_quality_actions(
    client: TestClient,
    db_session: Session,
) -> None:
    source_category = Category(slug="operator-source-category", name="Source Category")
    target_category = Category(slug="operator-target-category", name="Target Category")
    db_session.add_all([source_category, target_category])
    db_session.flush()
    product = _source_product(
        db_session,
        source_id="operator-category-source",
        category_id=source_category.id,
    )

    category_response = client.put(
        f"/products/{product.id}/category-override",
        json={
            "category_id": target_category.id,
            "actor": "reviewer",
            "reason": "source category was broad",
        },
    )
    data_problem_response = client.put(
        f"/products/{product.id}/data-problem",
        json={"is_not_product": True, "actor": "reviewer", "reason": "service card"},
    )
    category_dataset_response = client.get("/operator-decisions/datasets/category")

    assert category_response.status_code == 200
    assert data_problem_response.status_code == 200

    decisions_response = client.get(
        "/operator-decisions",
        params={"source_product_id": product.id, "limit": 10},
    )
    assert decisions_response.status_code == 200
    decisions = decisions_response.json()["items"]
    assert [decision["action"] for decision in decisions] == [
        "mark_data_problem",
        "set_category_override",
    ]
    assert decisions[0]["decision_type"] == "data_quality"
    assert decisions[1]["decision_type"] == "categorization"
    assert decisions[1]["previous_state"]["category_id"] == source_category.id
    assert decisions[1]["new_state"]["category_id"] == target_category.id

    assert category_dataset_response.status_code == 200
    examples = category_dataset_response.json()["items"]
    assert any(
        example["source_product_id"] == product.id
        and example["category_id"] == target_category.id
        and target_category.id in example["candidate_category_ids"]
        for example in examples
    )


def _canonical(session: Session, *, title: str) -> CanonicalProduct:
    category = Category(slug=f"operator-{title.casefold().replace(' ', '-')}", name=title)
    session.add(category)
    session.flush()
    return CanonicalProductRepository(session).create(
        CanonicalProductCreate(
            title=title,
            normalized_title=" ".join(title.casefold().split()),
            category_id=category.id,
        )
    )


def _source_product(
    session: Session,
    *,
    source_id: str,
    category_id: int | None = None,
) -> SourceProduct:
    shop = ShopRepository(session).upsert(
        ShopUpsert(source="2gis", source_id=f"shop-{source_id}", name="Decision Shop")
    )
    title = f"Operator Product {source_id}"
    return SourceProductRepository(session).upsert(
        SourceProductUpsert(
            shop_id=shop.id,
            source="2gis",
            source_product_id=source_id,
            title=title,
            normalized_title=" ".join(title.casefold().split()),
            category_id=category_id,
            raw={"catalog_eligibility": {"status": "eligible"}},
        )
    )
