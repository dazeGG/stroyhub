from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from stroyhub.catalog.quality_checks import (
    CatalogQualityCheckFilters,
    CatalogQualityCheckService,
)
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

from apps.admin_api.catalog_quality import get_session
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


def test_catalog_quality_checks_find_readiness_problems_and_resolve_duplicates(
    db_session: Session,
) -> None:
    now = datetime(2026, 5, 26, 8, 0, tzinfo=UTC)
    seeded = _seed_quality_check_data(db_session, now=now)

    report = CatalogQualityCheckService(db_session, now=now).report(
        CatalogQualityCheckFilters(limit=10_000)
    )
    codes = {finding.code for finding in report.findings.items}

    assert {
        "duplicate_normalized_product",
        "accepted_attribute_conflict",
        "stale_price",
        "stale_shop",
        "missing_critical_attributes",
        "uncategorized_product",
        "low_confidence_category",
    } <= codes
    assert report.summary.total == report.findings.total
    assert report.summary.blockers >= 1
    assert report.summary.by_code["accepted_attribute_conflict"] == 1

    duplicate = next(
        finding
        for finding in report.findings.items
        if finding.code == "duplicate_normalized_product"
    )
    assert duplicate.related_canonical_product_ids == (
        seeded["duplicate_a_id"],
        seeded["duplicate_b_id"],
    )

    conflict = next(
        finding
        for finding in report.findings.items
        if finding.code == "accepted_attribute_conflict"
    )
    assert conflict.source_product_id == seeded["conflict_source_id"]
    assert conflict.canonical_product_id == seeded["conflict_canonical_id"]
    assert conflict.metadata is not None
    assert conflict.metadata["conflicts"][0]["kind"] == "thickness"

    seeded["duplicate_b"].match_status = "inactive"
    db_session.flush()

    resolved_report = CatalogQualityCheckService(db_session, now=now).report(
        CatalogQualityCheckFilters(limit=10_000)
    )
    assert "duplicate_normalized_product" not in {
        finding.code for finding in resolved_report.findings.items
    }


def test_catalog_quality_findings_api_filters_and_paginates(
    client: TestClient,
    db_session: Session,
) -> None:
    seeded = _seed_quality_check_data(
        db_session,
        now=datetime(2026, 5, 26, 8, 0, tzinfo=UTC),
    )

    response = client.get(
        "/catalog-quality/findings",
        params={"code": "accepted_attribute_conflict", "limit": 100},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["blockers"] >= 1
    assert {
        item["source_product_id"]
        for item in payload["findings"]["items"]
    } >= {seeded["conflict_source_id"]}

    filtered = client.get(
        "/catalog-quality/findings",
        params={"code": "stale_price", "limit": 1, "offset": 0},
    )

    assert filtered.status_code == 200
    assert filtered.json()["findings"]["limit"] == 1
    assert filtered.json()["findings"]["items"][0]["code"] == "stale_price"


def _seed_quality_check_data(db_session: Session, *, now: datetime) -> dict[str, object]:
    category = Category(slug="quality-plywood", name="Quality Plywood")
    db_session.add(category)
    db_session.flush()

    fresh_shop = ShopRepository(db_session).upsert(
        ShopUpsert(
            source="2gis",
            source_id="quality-fresh-shop",
            name="Quality Fresh Shop",
            last_scraped_at=now,
            scrape_status="success",
        )
    )
    stale_shop = ShopRepository(db_session).upsert(
        ShopUpsert(
            source="2gis",
            source_id="quality-stale-shop",
            name="Quality Stale Shop",
            last_scraped_at=datetime(2026, 4, 1, 8, 0, tzinfo=UTC),
            scrape_status="success",
        )
    )

    canonical_repository = CanonicalProductRepository(db_session)
    duplicate_a = canonical_repository.create(
        CanonicalProductCreate(
            title="Фанера 4мм 1.52х1.52",
            normalized_title="фанера 4мм 1.52х1.52",
            category_id=category.id,
        )
    )
    duplicate_b = canonical_repository.create(
        CanonicalProductCreate(
            title="Фанера 4 мм 1.52х1.52",
            normalized_title="фанера 4мм 1.52х1.52",
            category_id=category.id,
        )
    )
    conflict_canonical = canonical_repository.create(
        CanonicalProductCreate(
            title="Фанера 4мм",
            normalized_title="фанера 4мм",
            category_id=category.id,
        )
    )

    products = SourceProductRepository(db_session)
    conflict_source = products.upsert(
        SourceProductUpsert(
            shop_id=fresh_shop.id,
            source="2gis",
            source_product_id="quality-conflict-source",
            title="Фанера 6мм",
            normalized_title="фанера 6мм",
            category_id=category.id,
        )
    )
    stale_price_product = products.upsert(
        SourceProductUpsert(
            shop_id=fresh_shop.id,
            source="2gis",
            source_product_id="quality-stale-price",
            title="Цемент M500 50кг",
            normalized_title="цемент m500 50кг",
            category_id=category.id,
        )
    )
    missing_attribute_product = products.upsert(
        SourceProductUpsert(
            shop_id=fresh_shop.id,
            source="2gis",
            source_product_id="quality-missing-attribute",
            title="Лафет",
            normalized_title="лафет",
            category_id=category.id,
        )
    )
    uncategorized_product = products.upsert(
        SourceProductUpsert(
            shop_id=fresh_shop.id,
            source="2gis",
            source_product_id="quality-uncategorized",
            title="Пескобетон 25кг",
            normalized_title="пескобетон 25кг",
        )
    )
    low_confidence_product = products.upsert(
        SourceProductUpsert(
            shop_id=fresh_shop.id,
            source="2gis",
            source_product_id="quality-low-confidence",
            title="Клей плиточный 25кг",
            normalized_title="клей плиточный 25кг",
            category_id=category.id,
            raw={
                "catalog_quality": {
                    "categorization": {
                        "status": "assigned",
                        "confidence": "0.500",
                    }
                }
            },
        )
    )

    prices = PriceSnapshotRepository(db_session)
    for product in (
        conflict_source,
        missing_attribute_product,
        uncategorized_product,
        low_confidence_product,
    ):
        prices.add(
            PriceSnapshotCreate(
                source_product_id=product.id,
                price=Decimal("100.00"),
                parsed_at=now,
            )
        )
    prices.add(
        PriceSnapshotCreate(
            source_product_id=stale_price_product.id,
            price=Decimal("100.00"),
            parsed_at=datetime(2026, 4, 1, 8, 0, tzinfo=UTC),
        )
    )

    ProductMatchRepository(db_session).create(
        ProductMatchCreate(
            canonical_product_id=conflict_canonical.id,
            source_product_id=conflict_source.id,
            confidence=Decimal("1.000"),
            method="manual",
            status="accepted",
            reviewed_at=now,
            reviewed_by="tester",
        )
    )
    db_session.flush()
    return {
        "duplicate_a_id": duplicate_a.id,
        "duplicate_b_id": duplicate_b.id,
        "duplicate_b": duplicate_b,
        "conflict_source_id": conflict_source.id,
        "conflict_canonical_id": conflict_canonical.id,
        "stale_shop_id": stale_shop.id,
    }
