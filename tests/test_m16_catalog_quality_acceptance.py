from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from stroyhub.catalog.quality_pipeline import CatalogQualityPipeline
from stroyhub.core.config import settings
from stroyhub.db import (
    CanonicalProductCreate,
    CanonicalProductRepository,
    CategoryRepository,
    CategoryUpsert,
    PriceSnapshotCreate,
    PriceSnapshotRepository,
    ShopRepository,
    ShopUpsert,
    SourceProductRepository,
    SourceProductUpsert,
)
from stroyhub.models import ProductMatch, SourceProduct
from stroyhub.parsers.common import normalize_title

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


def test_m16_catalog_quality_acceptance_flow(
    client: TestClient,
    db_session: Session,
) -> None:
    data = _seed_acceptance_scenario(db_session)
    result = CatalogQualityPipeline(db_session).run_for_shop(
        data["shop_id"],
        processed_at=datetime(2026, 5, 26, 3, 0, tzinfo=UTC),
    )
    _remove_cached_canonical_id(db_session, data["stale_attach_id"])

    assert result.products_seen == 6
    assert result.products_processed == 6
    assert result.products_failed == 0

    dashboard = client.get(
        "/catalog-workflows/dashboard",
        params={"shop": data["shop_id"]},
    )
    auto_queue = client.get(
        "/catalog-workflows/queues/auto_acceptable",
        params={"shop": data["shop_id"], "limit": 10},
    )
    review_queue = client.get(
        "/catalog-workflows/queues/review_needed",
        params={"shop": data["shop_id"], "limit": 10},
    )
    problem_queue = client.get(
        "/catalog-workflows/queues/data_problems",
        params={"shop": data["shop_id"], "limit": 10},
    )

    assert dashboard.status_code == 200
    counts = {item["queue"]: item["count"] for item in dashboard.json()["counts"]}
    assert counts == {
        "auto_acceptable": 3,
        "review_needed": 2,
        "data_problems": 1,
        "possible_duplicates": 3,
        "normalized_items": 0,
    }

    assert auto_queue.status_code == 200
    auto_items = auto_queue.json()["items"]
    auto_ids = {item["id"] for item in auto_items}
    assert auto_ids == {
        data["auto_create_id"],
        data["safe_attach_id"],
        data["stale_attach_id"],
    }
    assert data["category_conflict_id"] not in auto_ids
    assert data["ambiguous_id"] not in auto_ids
    assert data["data_problem_id"] not in auto_ids
    assert all(
        "normalization" in {reason["stage"] for reason in item["reasons"]}
        for item in auto_items
    )

    assert review_queue.status_code == 200
    review_items = review_queue.json()["items"]
    review_ids = {item["id"] for item in review_items}
    assert review_ids == {data["ambiguous_id"], data["category_conflict_id"]}
    conflict_item = next(
        item for item in review_items if item["id"] == data["category_conflict_id"]
    )
    assert any(
        reason["stage"] == "categorization" and reason["status"] == "needs_review"
        for reason in conflict_item["reasons"]
    )

    assert problem_queue.status_code == 200
    problem_ids = {item["id"] for item in problem_queue.json()["items"]}
    assert problem_ids == {data["data_problem_id"]}

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
            "actor": "acceptance",
            "reason": "M16 acceptance scenario",
        },
    )

    assert dry_run.status_code == 200
    dry_payload = dry_run.json()
    assert dry_payload["total"] == 3
    assert dry_payload["would_accept"] == 2
    assert dry_payload["skipped"] == 1
    assert {
        item["reason"] for item in dry_payload["items"] if item["status"] == "skipped"
    } == {"missing_canonical_product_id"}

    assert apply.status_code == 200
    apply_payload = apply.json()
    assert apply_payload["accepted"] == 2
    assert apply_payload["skipped"] == 1
    assert {
        item["source_product_id"]
        for item in apply_payload["items"]
        if item["status"] == "accepted"
    } == {data["auto_create_id"], data["safe_attach_id"]}
    assert {
        item["source_product_id"]
        for item in apply_payload["items"]
        if item["status"] == "skipped"
    } == {data["stale_attach_id"]}

    normalized_queue = client.get(
        "/catalog-workflows/queues/normalized_items",
        params={"shop": data["shop_id"], "limit": 10},
    )
    post_dashboard = client.get(
        "/catalog-workflows/dashboard",
        params={"shop": data["shop_id"]},
    )
    decisions = client.get(
        "/operator-decisions",
        params={"decision_type": "normalization", "source_product_id": data["auto_create_id"]},
    )

    assert normalized_queue.status_code == 200
    normalized_ids = {item["id"] for item in normalized_queue.json()["items"]}
    assert normalized_ids == {data["auto_create_id"], data["safe_attach_id"]}
    assert normalized_ids.isdisjoint(
        {
            data["ambiguous_id"],
            data["category_conflict_id"],
            data["data_problem_id"],
            data["stale_attach_id"],
        }
    )

    assert post_dashboard.status_code == 200
    post_counts = {item["queue"]: item["count"] for item in post_dashboard.json()["counts"]}
    assert post_counts == {
        "auto_acceptable": 1,
        "review_needed": 2,
        "data_problems": 1,
        "possible_duplicates": 2,
        "normalized_items": 2,
    }
    assert decisions.status_code == 200
    assert decisions.json()["total"] == 1

    accepted_count = db_session.scalar(
        select(func.count())
        .select_from(ProductMatch)
        .where(
            ProductMatch.source_product_id.in_(
                [data["auto_create_id"], data["safe_attach_id"]]
            ),
            ProductMatch.status == "accepted",
        )
    )
    unsafe_accepted_count = db_session.scalar(
        select(func.count())
        .select_from(ProductMatch)
        .where(
            ProductMatch.source_product_id.in_(
                [
                    data["ambiguous_id"],
                    data["category_conflict_id"],
                    data["data_problem_id"],
                    data["stale_attach_id"],
                ]
            ),
            ProductMatch.status == "accepted",
        )
    )
    assert accepted_count == 2
    assert unsafe_accepted_count == 0


def _seed_acceptance_scenario(db_session: Session) -> dict[str, int]:
    category_repository = CategoryRepository(db_session)
    parent = category_repository.upsert(
        CategoryUpsert(slug="mixes_aggregates", name="Смеси и сыпучие материалы")
    )
    cement = category_repository.upsert(
        CategoryUpsert(slug="cement", name="Цемент", parent_id=parent.id)
    )
    shop = ShopRepository(db_session).upsert(
        ShopUpsert(source="unicom", source_id="m16-acceptance-shop", name="M16 Shop")
    )
    canonical_repository = CanonicalProductRepository(db_session)
    canonical_repository.create(
        CanonicalProductCreate(
            title="Приемка Цемент М500 50кг",
            normalized_title=normalize_title("Приемка Цемент М500 50кг"),
            category_id=cement.id,
        )
    )
    for suffix in ("А", "Б"):
        canonical_repository.create(
            CanonicalProductCreate(
                title=f"Приемка Цемент М400 50кг {suffix}",
                normalized_title=normalize_title("Приемка Цемент М400 50кг"),
                category_id=cement.id,
            )
        )
    canonical_repository.create(
        CanonicalProductCreate(
            title="Приемка Цемент М300 50кг",
            normalized_title=normalize_title("Приемка Цемент М300 50кг"),
            category_id=cement.id,
        )
    )

    products = SourceProductRepository(db_session)
    auto_create = _source_product(
        products,
        shop_id=shop.id,
        source_product_id="m16-auto-create",
        title="Приемка Цемент М600 50кг",
        category_raw="Цемент",
    )
    safe_attach = _source_product(
        products,
        shop_id=shop.id,
        source_product_id="m16-safe-attach",
        title="Приемка Цемент М500 50кг",
        category_raw="Цемент",
    )
    ambiguous = _source_product(
        products,
        shop_id=shop.id,
        source_product_id="m16-ambiguous",
        title="Приемка Цемент М400 50кг",
        category_raw="Цемент",
    )
    stale_attach = _source_product(
        products,
        shop_id=shop.id,
        source_product_id="m16-stale-attach",
        title="Приемка Цемент М300 50кг",
        category_raw="Цемент",
    )
    data_problem = _source_product(
        products,
        shop_id=shop.id,
        source_product_id="m16-data-problem",
        title="Приемка услуга доставки цемента",
        category_raw="Цемент",
        is_not_product=True,
    )
    category_conflict = _source_product(
        products,
        shop_id=shop.id,
        source_product_id="m16-category-conflict",
        title="Цемент профнастил 50кг",
        category_raw=None,
    )
    prices = PriceSnapshotRepository(db_session)
    for index, product_id in enumerate(
        [
            auto_create.id,
            safe_attach.id,
            ambiguous.id,
            stale_attach.id,
            data_problem.id,
            category_conflict.id,
        ],
        start=1,
    ):
        prices.add(
            PriceSnapshotCreate(
                source_product_id=product_id,
                price=Decimal(500 + index),
                parsed_at=datetime(2026, 5, 26, 2, index, tzinfo=UTC),
            )
        )

    return {
        "shop_id": shop.id,
        "auto_create_id": auto_create.id,
        "safe_attach_id": safe_attach.id,
        "ambiguous_id": ambiguous.id,
        "stale_attach_id": stale_attach.id,
        "data_problem_id": data_problem.id,
        "category_conflict_id": category_conflict.id,
    }


def _source_product(
    repository: SourceProductRepository,
    *,
    shop_id: int,
    source_product_id: str,
    title: str,
    category_raw: str | None,
    is_not_product: bool | None = None,
) -> SourceProduct:
    return repository.upsert(
        SourceProductUpsert(
            shop_id=shop_id,
            source="unicom",
            source_product_id=source_product_id,
            title=title,
            normalized_title=normalize_title(title),
            category_raw=category_raw,
            is_not_product=is_not_product,
        )
    )


def _remove_cached_canonical_id(db_session: Session, source_product_id: int) -> None:
    source_product = db_session.get(SourceProduct, source_product_id)
    assert source_product is not None
    assert source_product.raw is not None
    quality = dict(source_product.raw["catalog_quality"])
    normalization = dict(quality["normalization"])
    normalization.pop("canonical_product_id", None)
    quality["normalization"] = normalization
    source_product.raw = {**source_product.raw, "catalog_quality": quality}
    db_session.flush()
