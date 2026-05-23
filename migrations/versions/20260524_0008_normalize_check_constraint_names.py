"""Normalize check constraint names without duplicated table prefixes.

Revision ID: 20260524_0008
Revises: 20260524_0007
Create Date: 2026-05-24 00:00:00
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260524_0008"
down_revision: str | Sequence[str] | None = "20260524_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RENAME_PAIRS: tuple[tuple[str, str, str], ...] = (
    (
        "shop_identities",
        "ck_shop_identities_ck_shop_identities_status_known",
        "ck_shop_identities_status_known",
    ),
    ("shops", "ck_shops_ck_shops_source_type_known", "ck_shops_source_type_known"),
    ("shops", "ck_shops_ck_shops_scrape_status_known", "ck_shops_scrape_status_known"),
    ("shops", "ck_shops_ck_shops_scrape_interval_positive", "ck_shops_scrape_interval_positive"),
    ("shops", "ck_shops_ck_shops_error_count_nonnegative", "ck_shops_error_count_nonnegative"),
    (
        "shop_source_candidates",
        "ck_shop_source_candidates_ck_shop_source_candidates_source_known",
        "ck_shop_source_candidates_source_known",
    ),
    (
        "shop_source_candidates",
        "ck_shop_source_candidates_ck_shop_source_candidates_status_known",
        "ck_shop_source_candidates_status_known",
    ),
    (
        "shop_source_candidates",
        "ck_shop_source_candidates_ck_shop_source_candidates_product_count_nonnegative",
        "ck_shop_source_candidates_product_count_nonnegative",
    ),
    (
        "shop_source_candidates",
        "ck_shop_source_candidates_ck_shop_source_candidates_priced_product_count_nonnegative",
        "ck_shop_source_candidates_priced_product_count_nonnegative",
    ),
    (
        "shop_source_candidates",
        "ck_shop_source_candidates_ck_shop_source_candidates_priority_nonnegative",
        "ck_shop_source_candidates_priority_nonnegative",
    ),
    (
        "source_products",
        "ck_source_products_ck_source_products_has_stable_identity",
        "ck_source_products_has_stable_identity",
    ),
    (
        "category_overrides",
        "ck_category_overrides_ck_category_overrides_status_known",
        "ck_category_overrides_status_known",
    ),
    (
        "canonical_products",
        "ck_canonical_products_ck_canonical_products_match_status_known",
        "ck_canonical_products_match_status_known",
    ),
    (
        "product_matches",
        "ck_product_matches_ck_product_matches_confidence_range",
        "ck_product_matches_confidence_range",
    ),
    (
        "product_matches",
        "ck_product_matches_ck_product_matches_status_known",
        "ck_product_matches_status_known",
    ),
    (
        "product_matches",
        "ck_product_matches_ck_product_matches_method_known",
        "ck_product_matches_method_known",
    ),
    (
        "price_snapshots",
        "ck_price_snapshots_ck_price_snapshots_price_nonnegative",
        "ck_price_snapshots_price_nonnegative",
    ),
    ("scrape_runs", "ck_scrape_runs_ck_scrape_runs_status_known", "ck_scrape_runs_status_known"),
    (
        "scrape_runs",
        "ck_scrape_runs_ck_scrape_runs_items_seen_nonnegative",
        "ck_scrape_runs_items_seen_nonnegative",
    ),
    (
        "scrape_runs",
        "ck_scrape_runs_ck_scrape_runs_items_saved_nonnegative",
        "ck_scrape_runs_items_saved_nonnegative",
    ),
)


def _rename_if_present(table_name: str, old_name: str, new_name: str) -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = '{old_name}'
            ) AND NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = '{new_name}'
            ) THEN
                EXECUTE 'ALTER TABLE {table_name} RENAME CONSTRAINT {old_name} TO {new_name}';
            END IF;
        END
        $$;
        """
    )


def upgrade() -> None:
    for table_name, old_name, new_name in RENAME_PAIRS:
        _rename_if_present(table_name, old_name, new_name)


def downgrade() -> None:
    for table_name, old_name, new_name in reversed(RENAME_PAIRS):
        _rename_if_present(table_name, new_name, old_name)
