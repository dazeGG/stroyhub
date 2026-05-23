"""add db check constraints for core invariants

Revision ID: 20260524_0007
Revises: 20260523_0006
Create Date: 2026-05-24 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260524_0007"
down_revision: str | None = "20260523_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _validate_existing_data()

    op.create_check_constraint(
        "ck_shops_scrape_status_known",
        "shops",
        "scrape_status IN ("
        "'new', 'ok', 'scheduled', 'running', 'success', 'partial', 'failed', 'disabled'"
        ")",
    )
    op.create_check_constraint(
        "ck_shops_scrape_interval_positive",
        "shops",
        "scrape_interval > 0",
    )
    op.create_check_constraint(
        "ck_shops_error_count_nonnegative",
        "shops",
        "error_count >= 0",
    )

    op.create_check_constraint(
        "ck_source_products_has_stable_identity",
        "source_products",
        "(NULLIF(BTRIM(COALESCE(source_product_id, '')), '') IS NOT NULL) OR "
        "(NULLIF(BTRIM(COALESCE(fingerprint, '')), '') IS NOT NULL)",
    )

    op.create_check_constraint(
        "ck_shop_source_candidates_product_count_nonnegative",
        "shop_source_candidates",
        "product_count >= 0",
    )
    op.create_check_constraint(
        "ck_shop_source_candidates_priced_product_count_nonnegative",
        "shop_source_candidates",
        "priced_product_count >= 0",
    )
    op.create_check_constraint(
        "ck_shop_source_candidates_priority_nonnegative",
        "shop_source_candidates",
        "priority >= 0",
    )

    op.create_check_constraint(
        "ck_category_overrides_status_known",
        "category_overrides",
        "status IN ('active', 'replaced', 'reverted')",
    )

    op.create_check_constraint(
        "ck_canonical_products_match_status_known",
        "canonical_products",
        "match_status IN ('active', 'inactive')",
    )

    op.create_check_constraint(
        "ck_product_matches_confidence_range",
        "product_matches",
        "confidence >= 0 AND confidence <= 1",
    )
    op.create_check_constraint(
        "ck_product_matches_status_known",
        "product_matches",
        "status IN ('candidate', 'accepted', 'rejected', 'superseded')",
    )
    op.create_check_constraint(
        "ck_product_matches_method_known",
        "product_matches",
        "method IN ("
        "'exact_title', 'exact_normalized_title', 'token_similarity', "
        "'attribute_rules', 'manual', 'embedding'"
        ")",
    )

    op.create_check_constraint(
        "ck_price_snapshots_price_nonnegative",
        "price_snapshots",
        "price IS NULL OR price >= 0",
    )

    op.create_check_constraint(
        "ck_scrape_runs_status_known",
        "scrape_runs",
        "status IN ('running', 'success', 'partial', 'failed', 'skipped')",
    )
    op.create_check_constraint(
        "ck_scrape_runs_items_seen_nonnegative",
        "scrape_runs",
        "items_seen >= 0",
    )
    op.create_check_constraint(
        "ck_scrape_runs_items_saved_nonnegative",
        "scrape_runs",
        "items_saved >= 0",
    )


def downgrade() -> None:
    op.drop_constraint("ck_scrape_runs_items_saved_nonnegative", "scrape_runs", type_="check")
    op.drop_constraint("ck_scrape_runs_items_seen_nonnegative", "scrape_runs", type_="check")
    op.drop_constraint("ck_scrape_runs_status_known", "scrape_runs", type_="check")
    op.drop_constraint("ck_price_snapshots_price_nonnegative", "price_snapshots", type_="check")
    op.drop_constraint("ck_product_matches_method_known", "product_matches", type_="check")
    op.drop_constraint("ck_product_matches_status_known", "product_matches", type_="check")
    op.drop_constraint("ck_product_matches_confidence_range", "product_matches", type_="check")
    op.drop_constraint(
        "ck_canonical_products_match_status_known",
        "canonical_products",
        type_="check",
    )
    op.drop_constraint("ck_category_overrides_status_known", "category_overrides", type_="check")
    op.drop_constraint(
        "ck_shop_source_candidates_priority_nonnegative",
        "shop_source_candidates",
        type_="check",
    )
    op.drop_constraint(
        "ck_shop_source_candidates_priced_product_count_nonnegative",
        "shop_source_candidates",
        type_="check",
    )
    op.drop_constraint(
        "ck_shop_source_candidates_product_count_nonnegative",
        "shop_source_candidates",
        type_="check",
    )
    op.drop_constraint(
        "ck_source_products_has_stable_identity",
        "source_products",
        type_="check",
    )
    op.drop_constraint("ck_shops_error_count_nonnegative", "shops", type_="check")
    op.drop_constraint("ck_shops_scrape_interval_positive", "shops", type_="check")
    op.drop_constraint("ck_shops_scrape_status_known", "shops", type_="check")


def _validate_existing_data() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM source_products
                WHERE NULLIF(BTRIM(COALESCE(source_product_id, '')), '') IS NULL
                  AND NULLIF(BTRIM(COALESCE(fingerprint, '')), '') IS NULL
            ) THEN
                RAISE EXCEPTION 'source_products contains rows without stable identity';
            END IF;
        END
        $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM product_matches
                WHERE confidence < 0
                   OR confidence > 1
                   OR status NOT IN ('candidate', 'accepted', 'rejected', 'superseded')
                   OR method NOT IN (
                       'exact_title',
                       'exact_normalized_title',
                       'token_similarity',
                       'attribute_rules',
                       'manual',
                       'embedding'
                   )
            ) THEN
                RAISE EXCEPTION 'product_matches contains rows violating new constraints';
            END IF;
        END
        $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM shops
                WHERE scrape_status NOT IN (
                    'new',
                    'ok',
                    'scheduled',
                    'running',
                    'success',
                    'partial',
                    'failed',
                    'disabled'
                )
                   OR scrape_interval <= 0
                   OR error_count < 0
            ) THEN
                RAISE EXCEPTION 'shops contains rows violating new constraints';
            END IF;
        END
        $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM scrape_runs
                WHERE status NOT IN ('running', 'success', 'partial', 'failed', 'skipped')
                   OR items_seen < 0
                   OR items_saved < 0
            ) THEN
                RAISE EXCEPTION 'scrape_runs contains rows violating new constraints';
            END IF;
        END
        $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM category_overrides
                WHERE status NOT IN ('active', 'replaced', 'reverted')
            ) THEN
                RAISE EXCEPTION 'category_overrides contains rows violating new constraints';
            END IF;
        END
        $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM canonical_products
                WHERE match_status NOT IN ('active', 'inactive')
            ) THEN
                RAISE EXCEPTION 'canonical_products contains rows violating new constraints';
            END IF;
        END
        $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM shop_source_candidates
                WHERE product_count < 0
                   OR priced_product_count < 0
                   OR priority < 0
            ) THEN
                RAISE EXCEPTION 'shop_source_candidates contains rows violating new constraints';
            END IF;
        END
        $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM price_snapshots
                WHERE price < 0
            ) THEN
                RAISE EXCEPTION 'price_snapshots contains rows violating new constraints';
            END IF;
        END
        $$;
        """
    )
