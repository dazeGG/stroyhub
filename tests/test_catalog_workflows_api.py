from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
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
from stroyhub.models import CanonicalProduct, ProductMatch
from stroyhub.models.tables import Category

from apps.admin_api.catalog_workflows import get_session
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


def test_catalog_workflow_dashboard_and_queues(
    client: TestClient,
    db_session: Session,
) -> None:
    data = _seed_workflow_products(db_session)

    dashboard_response = client.get(
        "/catalog-workflows/dashboard",
        params={"shop": data["shop_id"]},
    )
    auto_queue_response = client.get(
        "/catalog-workflows/queues/auto_acceptable",
        params={"shop": data["shop_id"], "limit": 1, "offset": 1},
    )
    duplicate_response = client.get(
        "/catalog-workflows/queues/possible_duplicates",
        params={"shop": data["shop_id"]},
    )
    normalized_response = client.get(
        "/catalog-workflows/queues/normalized_items",
        params={"shop": data["shop_id"]},
    )

    assert dashboard_response.status_code == 200
    counts = {
        item["queue"]: item["count"]
        for item in dashboard_response.json()["counts"]
    }
    assert counts == {
        "auto_acceptable": 2,
        "review_needed": 1,
        "data_problems": 1,
        "possible_duplicates": 1,
        "normalized_items": 1,
    }

    assert auto_queue_response.status_code == 200
    auto_queue = auto_queue_response.json()
    assert auto_queue["total"] == 2
    assert auto_queue["limit"] == 1
    assert len(auto_queue["items"]) == 1
    auto_item = auto_queue["items"][0]
    assert auto_item["queue"] == "auto_acceptable"
    assert auto_item["catalog_quality"]["normalization"]["status"] == "ready_to_accept"
    assert {reason["stage"] for reason in auto_item["reasons"]} >= {
        "pipeline",
        "normalization",
    }

    assert duplicate_response.status_code == 200
    duplicate_item = duplicate_response.json()["items"][0]
    assert duplicate_item["title"] == "Workflow Duplicate Product"
    assert duplicate_item["match_summary"]["candidate_count"] == 1
    assert duplicate_item["candidate_matches"][0]["reason"] == {"method": "exact"}

    assert normalized_response.status_code == 200
    normalized_item = normalized_response.json()["items"][0]
    assert normalized_item["title"] == "Workflow Normalized Product"
    assert (
        normalized_item["match_summary"]["accepted_canonical_title"]
        == "Workflow Accepted Canonical"
    )


def test_catalog_workflow_auto_accept_batch_returns_per_item_results(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import stroyhub.catalog.product_match_decisions as product_match_decisions_module
    import stroyhub.catalog.workflow_queues as workflow_queues_module

    data = _seed_workflow_products(db_session)
    final_refresh_calls: list[tuple[int, bool]] = []

    class FailOnPerItemQualityRefresh:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("batch accept must not refresh quality per accepted item")

    class RecordFinalQualityRefresh:
        def __init__(self, _session: Session) -> None:
            pass

        def run_for_shop(
            self,
            shop_id: int,
            *,
            processed_at: object | None = None,
            generate_candidates: bool = True,
        ) -> object:
            assert processed_at is None
            final_refresh_calls.append((shop_id, generate_candidates))
            return object()

    monkeypatch.setattr(
        product_match_decisions_module,
        "CatalogQualityPipeline",
        FailOnPerItemQualityRefresh,
    )
    monkeypatch.setattr(
        workflow_queues_module,
        "CatalogQualityPipeline",
        RecordFinalQualityRefresh,
    )

    dry_run = client.post(
        "/catalog-workflows/batches/auto-accept",
        json={"shop_id": data["shop_id"], "dry_run": True, "limit": 10},
    )
    apply = client.post(
        "/catalog-workflows/batches/auto-accept",
        json={
            "shop_id": data["shop_id"],
            "dry_run": False,
            "limit": 10,
            "actor": "admin",
            "reason": "workflow batch",
        },
    )

    assert dry_run.status_code == 200
    assert dry_run.json()["total"] == 2
    assert dry_run.json()["would_accept"] == 2
    assert dry_run.json()["accepted"] == 0
    assert {item["action"] for item in dry_run.json()["items"]} == {
        "attach_to_existing",
        "create_normalized_product",
    }

    assert apply.status_code == 200
    payload = apply.json()
    assert payload["accepted"] == 2
    assert payload["skipped"] == 0
    assert {item["status"] for item in payload["items"]} == {"accepted"}

    accepted_count = db_session.scalar(
        select(func.count())
        .select_from(ProductMatch)
        .where(
            ProductMatch.source_product_id.in_(
                [data["auto_create_id"], data["duplicate_id"]]
            ),
            ProductMatch.status == "accepted",
        )
    )
    created_canonical = db_session.get(
        CanonicalProduct,
        next(
            item["canonical_product_id"]
            for item in payload["items"]
            if item["action"] == "create_normalized_product"
        ),
    )
    db_session.expire(data["duplicate_match"])
    assert accepted_count == 2
    assert created_canonical is not None
    assert created_canonical.title == "Workflow Auto Product 50кг"
    assert data["duplicate_match"].status == "accepted"
    assert final_refresh_calls == [(data["shop_id"], False)]


def _seed_workflow_products(db_session: Session) -> dict[str, Any]:
    category = Category(slug="workflow-category", name="Workflow Category")
    db_session.add(category)
    db_session.flush()
    shop = ShopRepository(db_session).upsert(
        ShopUpsert(source="2gis", source_id="workflow-shop", name="Workflow Shop")
    )
    canonical_repository = CanonicalProductRepository(db_session)
    duplicate_canonical = canonical_repository.create(
        CanonicalProductCreate(
            title="Workflow Duplicate Canonical",
            normalized_title="workflow duplicate product",
            category_id=category.id,
        )
    )
    accepted_canonical = canonical_repository.create(
        CanonicalProductCreate(
            title="Workflow Accepted Canonical",
            normalized_title="workflow normalized product",
            category_id=category.id,
        )
    )
    products = SourceProductRepository(db_session)
    auto_create = products.upsert(
        SourceProductUpsert(
            shop_id=shop.id,
            source="2gis",
            source_product_id="workflow-auto-create",
            title="Workflow Auto Product 50кг",
            normalized_title="workflow auto product 50кг",
            category_id=category.id,
            raw=_raw_quality(
                action="create_normalized_product",
                status="ready_to_accept",
            ),
        )
    )
    duplicate = products.upsert(
        SourceProductUpsert(
            shop_id=shop.id,
            source="2gis",
            source_product_id="workflow-duplicate",
            title="Workflow Duplicate Product",
            normalized_title="workflow duplicate product",
            category_id=category.id,
            raw=_raw_quality(
                action="attach_to_existing",
                status="ready_to_accept",
                canonical_product_id=duplicate_canonical.id,
            ),
        )
    )
    review = products.upsert(
        SourceProductUpsert(
            shop_id=shop.id,
            source="2gis",
            source_product_id="workflow-review",
            title="Workflow Review Product",
            normalized_title="workflow review product",
            category_id=category.id,
            raw=_raw_quality(
                action="needs_review",
                status="needs_review",
                blockers=["weak_source_specificity"],
            ),
        )
    )
    data_problem = products.upsert(
        SourceProductUpsert(
            shop_id=shop.id,
            source="2gis",
            source_product_id="workflow-data-problem",
            title="Workflow Data Problem",
            normalized_title="workflow data problem",
            category_id=category.id,
            raw={
                "catalog_eligibility": {
                    "status": "eligible",
                    "reasons": ["test"],
                },
                "catalog_quality": {
                    "status": "failed",
                    "failed_stage": "attributes",
                    "attributes": {
                        "status": "failed",
                        "error": "bad attributes",
                    },
                },
            },
        )
    )
    normalized = products.upsert(
        SourceProductUpsert(
            shop_id=shop.id,
            source="2gis",
            source_product_id="workflow-normalized",
            title="Workflow Normalized Product",
            normalized_title="workflow normalized product",
            category_id=category.id,
            raw=_raw_quality(action="accepted", status="accepted"),
        )
    )
    match_repository = ProductMatchRepository(db_session)
    duplicate_match = match_repository.create(
        ProductMatchCreate(
            canonical_product_id=duplicate_canonical.id,
            source_product_id=duplicate.id,
            confidence=Decimal("1.000"),
            method="exact_normalized_title",
            status="candidate",
            reason={"method": "exact"},
        )
    )
    match_repository.create(
        ProductMatchCreate(
            canonical_product_id=accepted_canonical.id,
            source_product_id=normalized.id,
            confidence=Decimal("1.000"),
            method="manual",
            status="accepted",
        )
    )
    assert review.id > 0
    assert data_problem.id > 0
    return {
        "shop_id": shop.id,
        "auto_create_id": auto_create.id,
        "duplicate_id": duplicate.id,
        "duplicate_match": duplicate_match,
    }


def _raw_quality(
    *,
    action: str,
    status: str,
    canonical_product_id: int | None = None,
    blockers: list[str] | None = None,
) -> dict[str, object]:
    normalization: dict[str, object] = {
        "status": status,
        "action": action,
        "confidence": "0.970",
        "blockers": blockers or [],
        "processed_at": "2026-05-26T00:00:00+00:00",
    }
    if canonical_product_id is not None:
        normalization["canonical_product_id"] = canonical_product_id

    return {
        "catalog_eligibility": {
            "status": "eligible",
            "confidence": "1.000",
            "score": 100,
            "reasons": ["test"],
        },
        "catalog_quality": {
            "version": "test",
            "status": "processed",
            "processed_at": "2026-05-26T00:00:00+00:00",
            "cleanup": {"status": "passed"},
            "attributes": {"status": "passed", "reasons": ["attributes_ok"]},
            "categorization": {"status": "assigned", "reasons": ["rule"]},
            "normalization": normalization,
        },
    }
