from sqlalchemy import Index
from stroyhub.db.base import Base
from stroyhub.models import (
    CanonicalProduct,
    Category,
    CategoryOverride,
    PriceSnapshot,
    ProductMatch,
    ScrapeRun,
    Shop,
    ShopIdentity,
    ShopSourceCandidate,
    SourceProduct,
)


def _check_names(model: type[object]) -> set[str]:
    table = model.__table__  # type: ignore[attr-defined]
    return {
        constraint.name
        for constraint in table.constraints
        if constraint.name is not None
    }


def _has_check(model: type[object], name_suffix: str) -> bool:
    return any(name.endswith(name_suffix) for name in _check_names(model))


def test_m1_tables_are_registered_in_metadata() -> None:
    assert set(Base.metadata.tables) >= {
        "shops",
        "shop_identities",
        "shop_source_candidates",
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
    assert ShopIdentity.__tablename__ == "shop_identities"
    assert ShopSourceCandidate.__tablename__ == "shop_source_candidates"
    assert Category.__tablename__ == "categories"
    assert SourceProduct.__tablename__ == "source_products"
    assert PriceSnapshot.__tablename__ == "price_snapshots"
    assert ScrapeRun.__tablename__ == "scrape_runs"
    assert CanonicalProduct.__tablename__ == "canonical_products"
    assert ProductMatch.__tablename__ == "product_matches"


def test_shop_has_scheduling_columns() -> None:
    columns = Shop.__table__.columns

    assert "shop_identity_id" in columns
    assert "source_type" in columns
    assert "last_scraped_at" in columns
    assert "next_scrape_at" in columns
    assert "scrape_interval" in columns
    assert "scrape_status" in columns
    assert "error_count" in columns


def test_shop_identity_has_source_management_columns() -> None:
    columns = ShopIdentity.__table__.columns

    assert "display_name" in columns
    assert "website_url" in columns
    assert "preferred_source" in columns
    assert "status" in columns
    assert "locked_fields" in columns


def test_shop_source_candidate_has_review_queue_columns() -> None:
    columns = ShopSourceCandidate.__table__.columns

    assert "source_id" in columns
    assert "display_name" in columns
    assert "website_url" in columns
    assert "status" in columns
    assert "has_prices" in columns
    assert "has_website" in columns
    assert "priority" in columns
    assert "missing_since" in columns
    assert "approved_shop_id" in columns


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


def test_db_invariant_check_constraints_are_declared() -> None:
    assert _has_check(Shop, "ck_shops_scrape_status_known")
    assert _has_check(Shop, "ck_shops_scrape_interval_positive")
    assert _has_check(Shop, "ck_shops_error_count_nonnegative")
    assert _has_check(SourceProduct, "ck_source_products_has_stable_identity")
    assert _has_check(CategoryOverride, "ck_category_overrides_status_known")
    assert _has_check(CanonicalProduct, "ck_canonical_products_match_status_known")
    assert _has_check(ProductMatch, "ck_product_matches_confidence_range")
    assert _has_check(ProductMatch, "ck_product_matches_status_known")
    assert _has_check(ProductMatch, "ck_product_matches_method_known")
    assert _has_check(PriceSnapshot, "ck_price_snapshots_price_nonnegative")
    assert _has_check(ScrapeRun, "ck_scrape_runs_status_known")
