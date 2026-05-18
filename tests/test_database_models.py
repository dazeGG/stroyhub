from sqlalchemy import Index
from stroyhub.db.base import Base
from stroyhub.models import (
    CanonicalProduct,
    Category,
    PriceSnapshot,
    ProductMatch,
    ScrapeRun,
    Shop,
    SourceProduct,
)


def test_m1_tables_are_registered_in_metadata() -> None:
    assert set(Base.metadata.tables) >= {
        "shops",
        "categories",
        "source_products",
        "price_snapshots",
        "scrape_runs",
        "canonical_products",
        "product_matches",
    }


def test_source_product_partial_unique_indexes_are_declared() -> None:
    indexes = {index.name: index for index in SourceProduct.__table__.indexes}

    assert "uq_source_products_source_shop_source_product_id" in indexes
    assert "uq_source_products_source_shop_fingerprint" in indexes

    for index in indexes.values():
        if index.name is not None and index.name.startswith("uq_source_products_source_shop_"):
            assert isinstance(index, Index)
            assert index.unique
            assert index.dialect_options["postgresql"]["where"] is not None


def test_models_match_expected_table_names() -> None:
    assert Shop.__tablename__ == "shops"
    assert Category.__tablename__ == "categories"
    assert SourceProduct.__tablename__ == "source_products"
    assert PriceSnapshot.__tablename__ == "price_snapshots"
    assert ScrapeRun.__tablename__ == "scrape_runs"
    assert CanonicalProduct.__tablename__ == "canonical_products"
    assert ProductMatch.__tablename__ == "product_matches"


def test_shop_has_scheduling_columns() -> None:
    columns = Shop.__table__.columns

    assert "last_scraped_at" in columns
    assert "next_scrape_at" in columns
    assert "scrape_interval" in columns
    assert "scrape_status" in columns
    assert "error_count" in columns


def test_product_match_accepted_unique_index_is_declared() -> None:
    indexes = {index.name: index for index in ProductMatch.__table__.indexes}

    index = indexes["uq_product_matches_source_product_accepted"]

    assert isinstance(index, Index)
    assert index.unique
    assert index.dialect_options["postgresql"]["where"] is not None


def test_product_matching_models_have_expected_columns() -> None:
    canonical_columns = CanonicalProduct.__table__.columns
    match_columns = ProductMatch.__table__.columns

    assert "normalized_title" in canonical_columns
    assert "attributes" in canonical_columns
    assert "match_status" in canonical_columns
    assert "confidence" in match_columns
    assert "status" in match_columns
    assert "method" in match_columns
    assert "reason" in match_columns
