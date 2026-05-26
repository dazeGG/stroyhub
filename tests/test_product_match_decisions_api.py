from collections.abc import Iterator
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
    ProductMatchCreate,
    ProductMatchRepository,
    ShopRepository,
    ShopUpsert,
    SourceProductRepository,
    SourceProductUpsert,
)
from stroyhub.models import CanonicalProduct, SourceProduct
from stroyhub.models.tables import Category, ProductMatch

from apps.admin_api.main import create_app
from apps.admin_api.product_matches import get_session


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


def test_accept_product_match_creates_manual_accepted_match(
    client: TestClient,
    db_session: Session,
) -> None:
    canonical = _canonical(db_session, title="Accept Canonical")
    source_product = _source_product(db_session, source_id="accept-source")

    response = client.post(
        "/product-matches/accept",
        json={
            "canonical_product_id": canonical.id,
            "source_product_id": source_product.id,
            "actor": "admin",
            "reason": "looks exact",
        },
    )
    second_response = client.post(
        "/product-matches/accept",
        json={
            "canonical_product_id": canonical.id,
            "source_product_id": source_product.id,
            "actor": "admin",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert second_response.status_code == 200
    assert second_response.json()["id"] == payload["id"]
    assert payload["canonical_product_id"] == canonical.id
    assert payload["source_product_id"] == source_product.id
    assert payload["status"] == "accepted"
    assert payload["method"] == "manual"
    assert payload["confidence"] == "1.000"
    assert payload["reviewed_by"] == "admin"
    assert payload["reason"] == {"action": "accept", "note": "looks exact"}


def test_accept_product_match_conflicts_until_superseded(
    client: TestClient,
    db_session: Session,
) -> None:
    first_canonical = _canonical(db_session, title="First Canonical")
    second_canonical = _canonical(db_session, title="Second Canonical")
    source_product = _source_product(db_session, source_id="supersede-source")
    first_match = ProductMatchRepository(db_session).create(
        ProductMatchCreate(
            canonical_product_id=first_canonical.id,
            source_product_id=source_product.id,
            confidence=Decimal("1.000"),
            method="manual",
            status="accepted",
        )
    )

    conflict_response = client.post(
        "/product-matches/accept",
        json={
            "canonical_product_id": second_canonical.id,
            "source_product_id": source_product.id,
        },
    )
    supersede_response = client.post(
        "/product-matches/supersede",
        json={
            "canonical_product_id": second_canonical.id,
            "source_product_id": source_product.id,
            "actor": "admin",
            "reason": "better normalized product",
        },
    )

    db_session.expire(first_match)
    assert conflict_response.status_code == 409
    assert supersede_response.status_code == 200
    assert supersede_response.json()["status"] == "accepted"
    assert supersede_response.json()["canonical_product_id"] == second_canonical.id
    assert first_match.status == "superseded"
    assert first_match.reason == {
        "action": "supersede",
        "note": "better normalized product",
    }


def test_create_canonical_from_source_and_accept_links_in_one_transaction(
    client: TestClient,
    db_session: Session,
) -> None:
    category = Category(slug="create-followup-category", name="Create Followup Category")
    db_session.add(category)
    db_session.flush()
    title = "Create Followup Cement M500 50kg"
    source_product = _source_product(
        db_session,
        source_id="create-and-accept",
        title=title,
        category_id=category.id,
    )
    duplicate_source_product = _source_product(
        db_session,
        source_id="create-followup-candidate",
        title=title,
        category_id=category.id,
    )

    response = client.post(
        f"/product-matches/from-source/{source_product.id}/accept",
        json={"actor": "admin", "reason": "new normalized product"},
    )

    assert response.status_code == 201
    payload = response.json()
    canonical = db_session.get(CanonicalProduct, payload["canonical_product_id"])
    assert canonical is not None
    assert canonical.title == source_product.title
    assert payload["status"] == "accepted"
    assert payload["reason"] == {"action": "accept", "note": "new normalized product"}

    followup_candidate = db_session.scalar(
        select(ProductMatch).where(
            ProductMatch.canonical_product_id == canonical.id,
            ProductMatch.source_product_id == duplicate_source_product.id,
        )
    )
    assert followup_candidate is not None
    assert followup_candidate.status == "candidate"
    assert followup_candidate.method == "exact_normalized_title"


def test_accept_candidate_match_records_manual_method(
    client: TestClient,
    db_session: Session,
) -> None:
    canonical = _canonical(db_session, title="Candidate Accept Canonical")
    source_product = _source_product(db_session, source_id="candidate-accept-source")
    candidate = ProductMatchRepository(db_session).create(
        ProductMatchCreate(
            canonical_product_id=canonical.id,
            source_product_id=source_product.id,
            confidence=Decimal("0.850"),
            method="token_similarity",
            status="candidate",
        )
    )

    response = client.post(
        "/product-matches/accept",
        json={
            "canonical_product_id": canonical.id,
            "source_product_id": source_product.id,
            "actor": "admin",
        },
    )

    db_session.expire(candidate)
    assert response.status_code == 200
    assert response.json()["id"] == candidate.id
    assert response.json()["method"] == "manual"
    assert candidate.method == "manual"
    assert candidate.confidence == Decimal("1.000")


def test_reject_candidate_match_records_review_metadata(
    client: TestClient,
    db_session: Session,
) -> None:
    canonical = _canonical(db_session, title="Reject Canonical")
    source_product = _source_product(db_session, source_id="reject-source")
    candidate = ProductMatchRepository(db_session).create(
        ProductMatchCreate(
            canonical_product_id=canonical.id,
            source_product_id=source_product.id,
            confidence=Decimal("0.850"),
            method="token_similarity",
            status="candidate",
        )
    )

    response = client.post(
        f"/product-matches/{candidate.id}/reject",
        json={"actor": "admin", "reason": "different package"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == candidate.id
    assert payload["status"] == "rejected"
    assert payload["reviewed_by"] == "admin"
    assert payload["reason"] == {"action": "reject", "note": "different package"}


def test_product_match_validation_rejects_blank_or_too_long_actor(
    client: TestClient,
    db_session: Session,
) -> None:
    canonical = _canonical(db_session, title="Actor Validate Canonical")
    source_product = _source_product(db_session, source_id="actor-validate-source")

    blank_actor = client.post(
        "/product-matches/accept",
        json={
            "canonical_product_id": canonical.id,
            "source_product_id": source_product.id,
            "actor": "   ",
        },
    )
    long_actor = client.post(
        "/product-matches/accept",
        json={
            "canonical_product_id": canonical.id,
            "source_product_id": source_product.id,
            "actor": "a" * 121,
        },
    )

    assert blank_actor.status_code == 422
    assert long_actor.status_code == 422


def test_reject_non_candidate_match_returns_conflict(
    client: TestClient,
    db_session: Session,
) -> None:
    canonical = _canonical(db_session, title="Reject Accepted Canonical")
    source_product = _source_product(db_session, source_id="reject-accepted-source")
    accepted = ProductMatchRepository(db_session).create(
        ProductMatchCreate(
            canonical_product_id=canonical.id,
            source_product_id=source_product.id,
            confidence=Decimal("1.000"),
            method="manual",
            status="accepted",
        )
    )

    response = client.post(f"/product-matches/{accepted.id}/reject", json={})

    assert response.status_code == 409


def test_product_match_decisions_return_specific_not_found_codes(
    client: TestClient,
    db_session: Session,
) -> None:
    canonical = _canonical(db_session, title="Not Found Code Canonical")
    source_product = _source_product(db_session, source_id="not-found-code-source")

    missing_canonical = client.post(
        "/product-matches/accept",
        json={
            "canonical_product_id": 999999999,
            "source_product_id": source_product.id,
        },
    )
    missing_source = client.post(
        "/product-matches/accept",
        json={
            "canonical_product_id": canonical.id,
            "source_product_id": 999999999,
        },
    )
    missing_match = client.post("/product-matches/999999999/reject", json={})

    assert missing_canonical.status_code == 404
    assert missing_canonical.json()["code"] == "canonical_product_not_found"
    assert missing_source.status_code == 404
    assert missing_source.json()["code"] == "source_product_not_found"
    assert missing_match.status_code == 404
    assert missing_match.json()["code"] == "product_match_not_found"


def test_generate_candidates_persists_reviewable_matches_idempotently(
    client: TestClient,
    db_session: Session,
) -> None:
    canonical = _canonical(db_session, title="Generate Unique Cement M500 50kg")
    source_product = _source_product(
        db_session,
        source_id="generate-source",
        title="Generate Unique Cement M500 50kg",
        category_id=canonical.category_id,
    )

    response = client.post(
        "/product-matches/generate-candidates",
        json={"source": "2gis", "category_id": canonical.category_id, "min_confidence": 0.9},
    )
    second_response = client.post(
        "/product-matches/generate-candidates",
        json={"source": "2gis", "category_id": canonical.category_id, "min_confidence": 0.9},
    )

    match = db_session.scalar(
        select(ProductMatch).where(
            ProductMatch.source_product_id == source_product.id,
            ProductMatch.canonical_product_id == canonical.id,
        )
    )
    assert response.status_code == 200
    assert response.json()["candidates_created"] == 1
    assert second_response.status_code == 200
    assert second_response.json()["candidates_created"] == 0
    assert second_response.json()["candidates_skipped_existing"] >= 1
    assert match is not None
    assert match.status == "candidate"
    assert match.method == "exact_normalized_title"


def test_generate_candidates_deduplicates_references_in_same_run(
    client: TestClient,
    db_session: Session,
) -> None:
    canonical = _canonical(db_session, title="Duplicate Reference Cement M500 50kg")
    accepted_source = _source_product(
        db_session,
        source_id="duplicate-reference-accepted-source",
        title="Duplicate Reference Cement M500 50kg",
        category_id=canonical.category_id,
    )
    source_product = _source_product(
        db_session,
        source_id="duplicate-reference-source",
        title="Duplicate Reference Cement M500 50kg",
        category_id=canonical.category_id,
    )
    ProductMatchRepository(db_session).create(
        ProductMatchCreate(
            canonical_product_id=canonical.id,
            source_product_id=accepted_source.id,
            confidence=Decimal("1.000"),
            method="manual",
            status="accepted",
        )
    )

    response = client.post(
        "/product-matches/generate-candidates",
        json={"source": "2gis", "category_id": canonical.category_id, "min_confidence": 0.9},
    )

    match_count = db_session.scalar(
        select(func.count())
        .select_from(ProductMatch)
        .where(
            ProductMatch.source_product_id == source_product.id,
            ProductMatch.canonical_product_id == canonical.id,
        )
    )
    assert response.status_code == 200
    assert response.json()["candidates_created"] == 1
    assert match_count == 1


def test_generate_candidates_skips_ineligible_and_blocked_products(
    client: TestClient,
    db_session: Session,
) -> None:
    canonical = _canonical(db_session, title="Blocked Unique Cement M500 50kg")
    ineligible_product = _source_product(
        db_session,
        source_id="generate-ineligible",
        title="Blocked Unique Cement M500 50kg",
        category_id=canonical.category_id,
        raw={"catalog_eligibility": {"status": "ineligible"}},
        is_not_product=True,
    )
    blocked_product = _source_product(
        db_session,
        source_id="generate-blocked",
        title="Blocked Unique Cement M500 25kg",
        category_id=canonical.category_id,
    )

    ineligible_response = client.post(
        "/product-matches/generate-candidates",
        json={
            "source": "2gis",
            "shop_id": ineligible_product.shop_id,
            "category_id": canonical.category_id,
            "min_confidence": 0,
        },
    )
    blocked_response = client.post(
        "/product-matches/generate-candidates",
        json={
            "source": "2gis",
            "shop_id": blocked_product.shop_id,
            "category_id": canonical.category_id,
            "min_confidence": 0,
        },
    )

    assert ineligible_response.status_code == 200
    assert ineligible_response.json()["source_products_considered"] == 0
    assert ineligible_response.json()["candidates_created"] == 0
    assert blocked_response.status_code == 200
    assert blocked_response.json()["source_products_considered"] == 1
    assert blocked_response.json()["candidates_created"] == 0


def test_generate_candidates_respects_category_blocking(
    client: TestClient,
    db_session: Session,
) -> None:
    category = Category(slug="generation-source-category", name="Source Category")
    other_category = Category(slug="generation-other-category", name="Other Category")
    db_session.add_all([category, other_category])
    db_session.flush()
    canonical = CanonicalProductRepository(db_session).create(
        CanonicalProductCreate(
            title="Category Block Cement M500 50kg",
            normalized_title="category block cement m500 50kg",
            category_id=other_category.id,
        )
    )
    source_product = _source_product(
        db_session,
        source_id="generate-category-blocked",
        title="Category Block Cement M500 50kg",
        category_id=category.id,
    )

    response = client.post(
        "/product-matches/generate-candidates",
        json={"source": "2gis", "shop_id": source_product.shop_id, "min_confidence": 0.9},
    )

    assert response.status_code == 200
    assert response.json()["source_products_considered"] == 1
    assert response.json()["reference_products_considered"] >= 1
    assert response.json()["candidates_created"] == 0
    assert response.json()["candidates_seen"] == 0
    assert canonical.id > 0


def test_auto_accept_candidates_dry_run_does_not_change_matches(
    client: TestClient,
    db_session: Session,
) -> None:
    canonical = _canonical(db_session, title="Auto Dry Run Cement M500 50kg")
    source_product = _source_product(
        db_session,
        source_id="auto-dry-run-source",
        title="Auto Dry Run Cement M500 50kg",
        category_id=canonical.category_id,
    )
    match = ProductMatchRepository(db_session).create(
        ProductMatchCreate(
            canonical_product_id=canonical.id,
            source_product_id=source_product.id,
            confidence=Decimal("1.000"),
            method="exact_normalized_title",
            status="candidate",
        )
    )

    response = client.post(
        "/product-matches/auto-accept-candidates",
        json={
            "source": "2gis",
            "shop_id": source_product.shop_id,
            "q": "Dry Run Cement",
            "dry_run": True,
        },
    )

    db_session.expire(match)
    payload = response.json()
    assert response.status_code == 200
    assert payload["dry_run"] is True
    assert payload["would_accept"] == 1
    assert payload["accepted"] == 0
    assert payload["items"][0]["match_id"] == match.id
    assert match.status == "candidate"


def test_auto_accept_candidates_accepts_safe_exact_match(
    client: TestClient,
    db_session: Session,
) -> None:
    canonical = _canonical(db_session, title="Auto Accept Cement M500 50kg")
    source_product = _source_product(
        db_session,
        source_id="auto-accept-source",
        title="Auto Accept Cement M500 50kg",
        category_id=canonical.category_id,
    )
    match = ProductMatchRepository(db_session).create(
        ProductMatchCreate(
            canonical_product_id=canonical.id,
            source_product_id=source_product.id,
            confidence=Decimal("1.000"),
            method="exact_normalized_title",
            status="candidate",
        )
    )

    response = client.post(
        "/product-matches/auto-accept-candidates",
        json={
            "source": "2gis",
            "shop_id": source_product.shop_id,
            "dry_run": False,
            "actor": "admin",
            "reason": "safe exact batch",
        },
    )

    db_session.expire(match)
    payload = response.json()
    assert response.status_code == 200
    assert payload["dry_run"] is False
    assert payload["would_accept"] == 1
    assert payload["accepted"] == 1
    assert match.status == "accepted"
    assert match.method == "exact_normalized_title"
    assert match.confidence == Decimal("1.000")
    assert match.reviewed_by == "admin"
    assert match.reason is not None
    assert match.reason["action"] == "auto_accept"
    assert match.reason["min_confidence"] == "1.000"
    assert match.reason["methods"] == ["exact_normalized_title"]
    assert match.reason["note"] == "safe exact batch"
    assert match.reason["decision"]["action"] == "attach_to_existing"
    assert match.reason["decision"]["positive_evidence"]
    assert match.reason["decision"]["negative_evidence"]


def test_auto_accept_candidates_skips_ambiguous_source_products(
    client: TestClient,
    db_session: Session,
) -> None:
    category = Category(slug="auto-ambiguous-category", name="Auto Ambiguous Category")
    db_session.add(category)
    db_session.flush()
    first_canonical = CanonicalProductRepository(db_session).create(
        CanonicalProductCreate(
            title="Auto Ambiguous Cement M500 50kg",
            normalized_title="auto ambiguous cement m500 50kg",
            category_id=category.id,
        )
    )
    second_canonical = CanonicalProductRepository(db_session).create(
        CanonicalProductCreate(
            title="Auto Ambiguous Cement M500 50kg duplicate",
            normalized_title="auto ambiguous cement m500 50kg duplicate",
            category_id=category.id,
        )
    )
    source_product = _source_product(
        db_session,
        source_id="auto-ambiguous-source",
        title="Auto Ambiguous Cement M500 50kg",
        category_id=category.id,
    )
    first_match = ProductMatchRepository(db_session).create(
        ProductMatchCreate(
            canonical_product_id=first_canonical.id,
            source_product_id=source_product.id,
            confidence=Decimal("1.000"),
            method="exact_normalized_title",
            status="candidate",
        )
    )
    second_match = ProductMatchRepository(db_session).create(
        ProductMatchCreate(
            canonical_product_id=second_canonical.id,
            source_product_id=source_product.id,
            confidence=Decimal("1.000"),
            method="exact_normalized_title",
            status="candidate",
        )
    )

    response = client.post(
        "/product-matches/auto-accept-candidates",
        json={
            "source": "2gis",
            "shop_id": source_product.shop_id,
            "dry_run": False,
        },
    )

    db_session.expire(first_match)
    db_session.expire(second_match)
    assert response.status_code == 200
    assert response.json()["candidates_seen"] == 2
    assert response.json()["would_accept"] == 0
    assert response.json()["accepted"] == 0
    assert response.json()["skipped_ambiguous"] == 1
    assert first_match.status == "candidate"
    assert second_match.status == "candidate"


def _canonical(session: Session, *, title: str) -> CanonicalProduct:
    category = Category(slug=f"category-{title.casefold().replace(' ', '-')}", name=title)
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
    title: str | None = None,
    category_id: int | None = None,
    raw: dict[str, object] | None = None,
    is_not_product: bool | None = None,
) -> SourceProduct:
    shop = ShopRepository(session).upsert(
        ShopUpsert(source="2gis", source_id=f"shop-{source_id}", name="Decision Shop")
    )
    selected_title = title or f"Decision Product {source_id}"
    return SourceProductRepository(session).upsert(
        SourceProductUpsert(
            shop_id=shop.id,
            source="2gis",
            source_product_id=source_id,
            title=selected_title,
            normalized_title=" ".join(selected_title.casefold().split()),
            category_id=category_id,
            raw=raw or {"catalog_eligibility": {"status": "eligible"}},
            is_not_product=is_not_product,
        )
    )
