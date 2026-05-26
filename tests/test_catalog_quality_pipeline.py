from collections.abc import Iterator

import pytest
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
    ShopRepository,
    ShopUpsert,
    SourceProductRepository,
    SourceProductUpsert,
)
from stroyhub.models import ProductMatch


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


def test_catalog_quality_pipeline_updates_product_stage_statuses(
    db_session: Session,
) -> None:
    shop = ShopRepository(db_session).upsert(
        ShopUpsert(source="2gis", source_id="quality-pipeline-shop", name="Pipeline Shop")
    )
    product = SourceProductRepository(db_session).upsert(
        SourceProductUpsert(
            shop_id=shop.id,
            source="2gis",
            source_product_id="quality-pipeline-product",
            title="Цемент М500 50кг",
            normalized_title="цемент м500 50кг",
            category_raw="Строительные смеси",
        )
    )

    result = CatalogQualityPipeline(db_session).run_for_shop(shop.id)

    db_session.expire(product)
    assert result.products_seen == 1
    assert result.products_processed == 1
    assert result.products_failed == 0
    assert product.category_id is not None
    assert product.raw is not None
    quality = product.raw["catalog_quality"]
    assert quality["status"] == "processed"
    assert quality["cleanup"]["status"] == "passed"
    assert quality["attributes"]["status"] == "passed"
    assert quality["categorization"]["status"] == "assigned"
    assert quality["normalization"]["action"] == "create_normalized_product"


def test_catalog_quality_pipeline_generates_candidates_idempotently(
    db_session: Session,
) -> None:
    parent_category = CategoryRepository(db_session).upsert(
        CategoryUpsert(slug="mixes_aggregates", name="Смеси и сыпучие материалы")
    )
    category = CategoryRepository(db_session).upsert(
        CategoryUpsert(slug="cement", name="Цемент", parent_id=parent_category.id)
    )
    shop = ShopRepository(db_session).upsert(
        ShopUpsert(source="unicom", source_id="quality-pipeline-candidate-shop", name="Shop")
    )
    product = SourceProductRepository(db_session).upsert(
        SourceProductUpsert(
            shop_id=shop.id,
            source="unicom",
            source_product_id="quality-pipeline-candidate-product",
            title="Цемент М500 50кг",
            normalized_title="цемент м500 50кг",
            category_id=category.id,
            category_raw="Цемент",
        )
    )
    canonical = CanonicalProductRepository(db_session).create(
        CanonicalProductCreate(
            title="Цемент М500 50кг",
            normalized_title="цемент м500 50кг",
            category_id=category.id,
        )
    )

    first = CatalogQualityPipeline(db_session).run_for_shop(shop.id)
    second = CatalogQualityPipeline(db_session).run_for_shop(shop.id)

    match_count = db_session.scalar(
        select(func.count())
        .select_from(ProductMatch)
        .where(
            ProductMatch.source_product_id == product.id,
            ProductMatch.canonical_product_id == canonical.id,
            ProductMatch.status == "candidate",
        )
    )
    db_session.expire(product)
    assert first.candidates_created == 1
    assert second.candidates_created == 0
    assert second.candidates_skipped_existing >= 1
    assert match_count == 1
    assert product.raw is not None
    assert product.raw["catalog_quality"]["normalization"]["action"] == "attach_to_existing"
