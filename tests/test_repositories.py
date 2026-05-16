from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
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
from stroyhub.models import PriceSnapshot, Shop, SourceProduct


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


def test_shop_repository_upserts_and_preserves_raw_payload(db_session: Session) -> None:
    repository = ShopRepository(db_session)

    shop = repository.upsert(
        ShopUpsert(
            source="2gis",
            source_id="branch-test-1",
            name="Initial Shop",
            address="Yakutsk",
            raw={"source": {"id": "branch-test-1"}},
        )
    )
    first_id = shop.id

    updated = repository.upsert(
        ShopUpsert(
            source="2gis",
            source_id="branch-test-1",
            name="Updated Shop",
            address="Yakutsk, Lenina 1",
            raw={"source": {"id": "branch-test-1", "updated": True}},
            scrape_status="success",
            error_count=2,
        )
    )

    count = db_session.scalar(
        select(func.count()).select_from(Shop).where(Shop.source_id == "branch-test-1")
    )

    assert updated.id == first_id
    assert updated.name == "Updated Shop"
    assert updated.raw == {"source": {"id": "branch-test-1", "updated": True}}
    assert updated.scrape_status == "success"
    assert updated.error_count == 2
    assert count == 1


def test_source_product_repository_upserts_by_source_product_id(
    db_session: Session,
) -> None:
    shop = ShopRepository(db_session).upsert(
        ShopUpsert(source="2gis", source_id="branch-test-2", name="Shop")
    )
    repository = SourceProductRepository(db_session)
    observed_at = datetime(2026, 5, 16, 10, 0, tzinfo=UTC)

    product = repository.upsert(
        SourceProductUpsert(
            shop_id=shop.id,
            source="2gis",
            source_product_id="product-1",
            title="Cement M500",
            normalized_title="cement m500",
            category_raw="Catalog / Cement",
            unit_raw="bag",
            raw={"id": "product-1", "price": "650"},
            observed_at=observed_at,
        )
    )
    first_id = product.id

    updated = repository.upsert(
        SourceProductUpsert(
            shop_id=shop.id,
            source="2gis",
            source_product_id="product-1",
            title="Cement M500 50kg",
            normalized_title="cement m500 50kg",
            category_raw="Catalog / Cement",
            unit_raw="50 kg",
            raw={"id": "product-1", "price": "700"},
            observed_at=datetime(2026, 5, 16, 11, 0, tzinfo=UTC),
        )
    )

    count = db_session.scalar(
        select(func.count()).select_from(SourceProduct).where(SourceProduct.shop_id == shop.id)
    )

    assert updated.id == first_id
    assert updated.title == "Cement M500 50kg"
    assert updated.unit_raw == "50 kg"
    assert updated.raw == {"id": "product-1", "price": "700"}
    assert updated.first_seen_at == observed_at
    assert count == 1


def test_source_product_repository_falls_back_to_fingerprint(
    db_session: Session,
) -> None:
    shop = ShopRepository(db_session).upsert(
        ShopUpsert(source="2gis", source_id="branch-test-3", name="Shop")
    )
    repository = SourceProductRepository(db_session)

    product = repository.upsert(
        SourceProductUpsert(
            shop_id=shop.id,
            source="2gis",
            fingerprint="stable-fingerprint",
            title="Sand",
            normalized_title="sand",
            raw={"title": "Sand"},
        )
    )

    updated = repository.upsert(
        SourceProductUpsert(
            shop_id=shop.id,
            source="2gis",
            fingerprint="stable-fingerprint",
            title="Sand washed",
            normalized_title="sand washed",
            raw={"title": "Sand washed"},
        )
    )

    assert updated.id == product.id
    assert updated.title == "Sand washed"
    assert updated.raw == {"title": "Sand washed"}


def test_source_product_repository_requires_stable_identity(db_session: Session) -> None:
    shop = ShopRepository(db_session).upsert(
        ShopUpsert(source="2gis", source_id="branch-test-4", name="Shop")
    )

    with pytest.raises(ValueError, match="source_product_id or fingerprint"):
        SourceProductRepository(db_session).upsert(
            SourceProductUpsert(
                shop_id=shop.id,
                source="2gis",
                title="Unknown product",
                normalized_title="unknown product",
            )
        )


def test_price_snapshot_repository_is_append_only(db_session: Session) -> None:
    shop = ShopRepository(db_session).upsert(
        ShopUpsert(source="2gis", source_id="branch-test-5", name="Shop")
    )
    product = SourceProductRepository(db_session).upsert(
        SourceProductUpsert(
            shop_id=shop.id,
            source="2gis",
            source_product_id="product-2",
            title="Brick",
            normalized_title="brick",
        )
    )
    repository = PriceSnapshotRepository(db_session)

    first = repository.add(
        PriceSnapshotCreate(
            source_product_id=product.id,
            price=Decimal("10.50"),
            raw={"price": "10.50"},
        )
    )
    second = repository.add(
        PriceSnapshotCreate(
            source_product_id=product.id,
            price=Decimal("10.50"),
            raw={"price": "10.50"},
        )
    )

    count = db_session.scalar(
        select(func.count())
        .select_from(PriceSnapshot)
        .where(PriceSnapshot.source_product_id == product.id)
    )

    assert first.id != second.id
    assert first.raw == {"price": "10.50"}
    assert second.raw == {"price": "10.50"}
    assert count == 2
