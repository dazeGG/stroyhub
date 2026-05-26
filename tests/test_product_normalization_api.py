from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
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
from stroyhub.models import CanonicalProduct, Category
from stroyhub.models.tables import ProductMatch

from apps.admin_api.main import create_app
from apps.admin_api.product_normalization import get_session


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


def test_normalization_queue_endpoint_returns_all_review_states(
    client: TestClient,
    db_session: Session,
) -> None:
    category = Category(slug="normalization-cement", name="Normalization Cement")
    db_session.add(category)
    db_session.flush()
    shop = ShopRepository(db_session).upsert(
        ShopUpsert(source="2gis", source_id="normalization-shop", name="Queue Shop")
    )
    products = SourceProductRepository(db_session)
    now = datetime(2026, 5, 23, 9, 0, tzinfo=UTC)

    ineligible = products.upsert(
        _product(
            shop_id=shop.id,
            source_product_id="normalization-ineligible",
            title="Гвозди",
            category_id=category.id,
            observed_at=now,
            raw={
                "catalog_eligibility": {
                    "status": "ineligible",
                    "confidence": "0.000",
                    "score": 0,
                    "reasons": ["non_exact_price", "generic_title"],
                }
            },
            is_not_product=True,
        )
    )
    needs_review = products.upsert(
        _product(
            shop_id=shop.id,
            source_product_id="normalization-needs-review",
            title="Смесь строительная",
            category_id=category.id,
            observed_at=now + timedelta(minutes=1),
            raw={
                "catalog_eligibility": {
                    "status": "needs_review",
                    "confidence": "0.650",
                    "score": 65,
                    "reasons": ["weak_product_specificity"],
                }
            },
        )
    )
    unmatched = products.upsert(
        _product(
            shop_id=shop.id,
            source_product_id="normalization-unmatched",
            title="Цемент М500 50кг",
            category_id=category.id,
            observed_at=now + timedelta(minutes=2),
        )
    )
    candidate = products.upsert(
        _product(
            shop_id=shop.id,
            source_product_id="normalization-candidate",
            title="Цемент М400 50кг",
            category_id=category.id,
            observed_at=now + timedelta(minutes=3),
        )
    )
    accepted = products.upsert(
        _product(
            shop_id=shop.id,
            source_product_id="normalization-accepted",
            title="Клей плиточный 25кг",
            category_id=category.id,
            observed_at=now + timedelta(minutes=4),
        )
    )
    PriceSnapshotRepository(db_session).add(
        PriceSnapshotCreate(
            source_product_id=unmatched.id,
            price=Decimal("650.00"),
            parsed_at=now + timedelta(minutes=5),
        )
    )
    canonical_repository = CanonicalProductRepository(db_session)
    candidate_canonical = canonical_repository.create(
        CanonicalProductCreate(title="Цемент М400 50кг", normalized_title="цемент м400 50кг")
    )
    accepted_canonical = canonical_repository.create(
        CanonicalProductCreate(title="Клей плиточный 25кг", normalized_title="клей плиточный 25кг")
    )
    matches = ProductMatchRepository(db_session)
    candidate_match = matches.create(
        ProductMatchCreate(
            canonical_product_id=candidate_canonical.id,
            source_product_id=candidate.id,
            confidence=Decimal("0.850"),
            method="token_similarity",
            status="candidate",
            reason={"token_overlap": ["цемент", "м400"]},
        )
    )
    accepted_match = matches.create(
        ProductMatchCreate(
            canonical_product_id=accepted_canonical.id,
            source_product_id=accepted.id,
            confidence=Decimal("1.000"),
            method="manual",
            status="accepted",
        )
    )

    response = client.get(
        "/product-normalization/queue",
        params={"source": "2gis", "category_id": category.id, "limit": 10},
    )

    assert response.status_code == 200
    payload = response.json()
    states_by_id = {item["id"]: item["state"] for item in payload["items"]}
    assert payload["total"] == 5
    assert states_by_id == {
        ineligible.id: "ineligible",
        needs_review.id: "needs_review",
        unmatched.id: "eligible_unmatched",
        candidate.id: "candidate_match",
        accepted.id: "accepted",
    }
    unmatched_item = next(item for item in payload["items"] if item["id"] == unmatched.id)
    candidate_item = next(item for item in payload["items"] if item["id"] == candidate.id)
    accepted_item = next(item for item in payload["items"] if item["id"] == accepted.id)
    assert unmatched_item["latest_price"]["price"] == "650.00"
    assert unmatched_item["shop"]["name"] == "Queue Shop"
    assert unmatched_item["category_name"] == "Normalization Cement"
    assert accepted_item["match_summary"] == {
        "accepted_match_id": accepted_match.id,
        "accepted_canonical_product_id": accepted_canonical.id,
        "accepted_canonical_title": "Клей плиточный 25кг",
        "candidate_count": 0,
        "rejected_count": 0,
    }
    assert candidate_item["candidate_matches"] == [
        {
            "id": candidate_match.id,
            "canonical_product_id": candidate_canonical.id,
            "canonical_title": "Цемент М400 50кг",
            "canonical_normalized_title": "цемент м400 50кг",
            "canonical_category_id": None,
            "confidence": "0.850",
            "method": "token_similarity",
            "reason": {"token_overlap": ["цемент", "м400"]},
        }
    ]


@pytest.mark.parametrize(
    ("state", "source_product_id"),
    [
        ("ineligible", "normalization-state-ineligible"),
        ("needs_review", "normalization-state-needs-review"),
        ("eligible_unmatched", "normalization-state-unmatched"),
        ("candidate_match", "normalization-state-candidate"),
        ("accepted", "normalization-state-accepted"),
    ],
)
def test_normalization_queue_endpoint_filters_each_state_before_pagination(
    client: TestClient,
    db_session: Session,
    state: str,
    source_product_id: str,
) -> None:
    category = Category(slug="normalization-states", name="Normalization States")
    db_session.add(category)
    db_session.flush()
    shop = ShopRepository(db_session).upsert(
        ShopUpsert(source="2gis", source_id="normalization-states-shop", name="States Shop")
    )
    products = SourceProductRepository(db_session)
    base_time = datetime(2026, 5, 23, 10, 0, tzinfo=UTC)
    created_products = {
        "ineligible": products.upsert(
            _product(
                shop_id=shop.id,
                source_product_id="normalization-state-ineligible",
                title="Гвозди",
                category_id=category.id,
                observed_at=base_time,
                raw={"catalog_eligibility": {"status": "ineligible"}},
                is_not_product=True,
            )
        ),
        "needs_review": products.upsert(
            _product(
                shop_id=shop.id,
                source_product_id="normalization-state-needs-review",
                title="Смесь",
                category_id=category.id,
                observed_at=base_time + timedelta(minutes=1),
                raw={"catalog_eligibility": {"status": "needs_review"}},
            )
        ),
        "eligible_unmatched": products.upsert(
            _product(
                shop_id=shop.id,
                source_product_id="normalization-state-unmatched",
                title="Цемент М500",
                category_id=category.id,
                observed_at=base_time + timedelta(minutes=2),
            )
        ),
        "candidate_match": products.upsert(
            _product(
                shop_id=shop.id,
                source_product_id="normalization-state-candidate",
                title="Цемент М400",
                category_id=category.id,
                observed_at=base_time + timedelta(minutes=3),
            )
        ),
        "accepted": products.upsert(
            _product(
                shop_id=shop.id,
                source_product_id="normalization-state-accepted",
                title="Клей плиточный",
                category_id=category.id,
                observed_at=base_time + timedelta(minutes=4),
            )
        ),
    }

    canonical_repository = CanonicalProductRepository(db_session)
    candidate_canonical = canonical_repository.create(
        CanonicalProductCreate(title="Цемент М400", normalized_title="цемент м400")
    )
    accepted_canonical = canonical_repository.create(
        CanonicalProductCreate(title="Клей плиточный", normalized_title="клей плиточный")
    )
    matches = ProductMatchRepository(db_session)
    matches.create(
        ProductMatchCreate(
            canonical_product_id=candidate_canonical.id,
            source_product_id=created_products["candidate_match"].id,
            confidence=Decimal("0.850"),
            method="token_similarity",
            status="candidate",
        )
    )
    matches.create(
        ProductMatchCreate(
            canonical_product_id=accepted_canonical.id,
            source_product_id=created_products["accepted"].id,
            confidence=Decimal("1.000"),
            method="manual",
            status="accepted",
        )
    )

    response = client.get(
        "/product-normalization/queue",
        params={"state": state, "category_id": category.id, "limit": 1, "offset": 0},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert len(payload["items"]) == 1
    assert payload["items"][0]["source_product_id"] == source_product_id


def test_normalization_queue_endpoint_filters_state_search_and_paginates(
    client: TestClient,
    db_session: Session,
) -> None:
    category = Category(slug="normalization-filter", name="Normalization Filter")
    db_session.add(category)
    db_session.flush()
    shop = ShopRepository(db_session).upsert(
        ShopUpsert(source="2gis", source_id="normalization-filter-shop", name="Filter Shop")
    )
    products = SourceProductRepository(db_session)
    matching_older = products.upsert(
        _product(
            shop_id=shop.id,
            source_product_id="normalization-filter-first",
            title="QueueUnique Cement M500 50kg Old",
            category_id=category.id,
            observed_at=datetime(2026, 5, 23, 9, 0, tzinfo=UTC),
        )
    )
    matching_newer = products.upsert(
        _product(
            shop_id=shop.id,
            source_product_id="normalization-filter-second",
            title="QueueUnique Cement M500 50kg New",
            category_id=category.id,
            observed_at=datetime(2026, 5, 23, 9, 1, tzinfo=UTC),
        )
    )
    products.upsert(
        _product(
            shop_id=shop.id,
            source_product_id="normalization-filter-third",
            title="Клей плиточный 25кг",
            category_id=category.id,
            observed_at=datetime(2026, 5, 23, 9, 2, tzinfo=UTC),
        )
    )
    products.upsert(
        _product(
            shop_id=shop.id,
            source_product_id="normalization-filter-blocked",
            title="Гвозди",
            category_id=category.id,
            raw={"catalog_eligibility": {"status": "ineligible"}},
            is_not_product=True,
            observed_at=datetime(2026, 5, 23, 9, 3, tzinfo=UTC),
        )
    )

    response = client.get(
        "/product-normalization/queue",
        params={
            "state": "eligible_unmatched",
            "q": "QueueUnique",
            "limit": 1,
            "offset": 1,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    assert payload["limit"] == 1
    assert payload["offset"] == 1
    assert [item["id"] for item in payload["items"]] == [matching_older.id]
    assert matching_newer.id != matching_older.id


def test_bulk_create_canonicals_skips_products_that_become_candidates(
    client: TestClient,
    db_session: Session,
) -> None:
    category = Category(slug="bulk-normalization-cement", name="Bulk Normalization Cement")
    db_session.add(category)
    db_session.flush()
    shop = ShopRepository(db_session).upsert(
        ShopUpsert(source="2gis", source_id="bulk-normalization-shop", name="Bulk Shop")
    )
    products = SourceProductRepository(db_session)
    first = products.upsert(
        _product(
            shop_id=shop.id,
            source_product_id="bulk-normalization-first",
            title="Bulk Cement M500 50kg",
            category_id=category.id,
            observed_at=datetime(2026, 5, 23, 9, 2, tzinfo=UTC),
        )
    )
    second = products.upsert(
        _product(
            shop_id=shop.id,
            source_product_id="bulk-normalization-second",
            title="Bulk Cement M500 50kg",
            category_id=category.id,
            observed_at=datetime(2026, 5, 23, 9, 1, tzinfo=UTC),
        )
    )

    dry_run_response = client.post(
        "/product-normalization/bulk-create-canonicals",
        json={"category_id": category.id, "dry_run": True},
    )
    apply_response = client.post(
        "/product-normalization/bulk-create-canonicals",
        json={
            "category_id": category.id,
            "dry_run": False,
            "actor": "admin",
            "reason": "bulk page normalization",
        },
    )

    assert dry_run_response.status_code == 200
    assert dry_run_response.json()["would_create"] == 2
    assert dry_run_response.json()["created"] == 0

    payload = apply_response.json()
    assert apply_response.status_code == 200
    assert payload["would_create"] == 2
    assert payload["created"] == 1
    assert payload["skipped_became_candidate"] == 1
    assert payload["followup_candidates_created"] == 1
    assert payload["items"][0]["source_product_id"] == first.id

    accepted_match = db_session.scalar(
        select(ProductMatch).where(
            ProductMatch.source_product_id == first.id,
            ProductMatch.status == "accepted",
        )
    )
    followup_candidate = db_session.scalar(
        select(ProductMatch).where(
            ProductMatch.source_product_id == second.id,
            ProductMatch.status == "candidate",
        )
    )
    canonical_count = db_session.scalar(
        select(func.count())
        .select_from(CanonicalProduct)
        .where(CanonicalProduct.title == "Bulk Cement M500 50kg")
    )
    assert accepted_match is not None
    assert accepted_match.reason == {"action": "accept", "note": "bulk page normalization"}
    assert followup_candidate is not None
    assert followup_candidate.canonical_product_id == accepted_match.canonical_product_id
    assert followup_candidate.method == "exact_normalized_title"
    assert canonical_count == 1


def _product(
    *,
    shop_id: int,
    source_product_id: str,
    title: str,
    category_id: int,
    raw: dict[str, object] | None = None,
    is_not_product: bool | None = None,
    observed_at: datetime | None = None,
) -> SourceProductUpsert:
    return SourceProductUpsert(
        shop_id=shop_id,
        source="2gis",
        source_product_id=source_product_id,
        title=title,
        normalized_title=" ".join(title.casefold().split()),
        category_id=category_id,
        category_raw="Цемент",
        raw=raw or {"catalog_eligibility": {"status": "eligible"}},
        is_not_product=is_not_product,
        observed_at=observed_at,
    )
