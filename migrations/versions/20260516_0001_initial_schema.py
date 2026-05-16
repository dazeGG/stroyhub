"""initial schema

Revision ID: 20260516_0001
Revises:
Create Date: 2026-05-16 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260516_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "shops",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("last_scraped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_scrape_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scrape_status", sa.Text(), server_default=sa.text("'new'"), nullable=False),
        sa.Column("error_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shops")),
        sa.UniqueConstraint("source", "source_id", name="uq_shops_source_source_id"),
    )
    op.create_index("ix_shops_next_scrape_at", "shops", ["next_scrape_at"], unique=False)
    op.create_index("ix_shops_scrape_status", "shops", ["scrape_status"], unique=False)

    op.create_table(
        "categories",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("parent_id", sa.BigInteger(), nullable=True),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"], ["categories.id"], name=op.f("fk_categories_parent_id_categories")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_categories")),
        sa.UniqueConstraint(
            "parent_id",
            "slug",
            name="uq_categories_parent_id_slug",
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index("ix_categories_parent_id", "categories", ["parent_id"], unique=False)

    op.create_table(
        "source_products",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("shop_id", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("source_product_id", sa.Text(), nullable=True),
        sa.Column("fingerprint", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("normalized_title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category_id", sa.BigInteger(), nullable=True),
        sa.Column("category_raw", sa.Text(), nullable=True),
        sa.Column("unit_raw", sa.Text(), nullable=True),
        sa.Column("image_url", sa.Text(), nullable=True),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            name=op.f("fk_source_products_category_id_categories"),
        ),
        sa.ForeignKeyConstraint(
            ["shop_id"], ["shops.id"], name=op.f("fk_source_products_shop_id_shops")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_products")),
    )
    op.create_index(
        "ix_source_products_category_id", "source_products", ["category_id"], unique=False
    )
    op.create_index(
        "ix_source_products_last_seen_at", "source_products", ["last_seen_at"], unique=False
    )
    op.create_index(
        "ix_source_products_normalized_title", "source_products", ["normalized_title"], unique=False
    )
    op.create_index("ix_source_products_shop_id", "source_products", ["shop_id"], unique=False)
    op.create_index(
        "uq_source_products_source_shop_fingerprint",
        "source_products",
        ["source", "shop_id", "fingerprint"],
        unique=True,
        postgresql_where=sa.text("fingerprint IS NOT NULL"),
    )
    op.create_index(
        "uq_source_products_source_shop_source_product_id",
        "source_products",
        ["source", "shop_id", "source_product_id"],
        unique=True,
        postgresql_where=sa.text("source_product_id IS NOT NULL"),
    )

    op.create_table(
        "price_snapshots",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("source_product_id", sa.BigInteger(), nullable=False),
        sa.Column("price", sa.Numeric(12, 2), nullable=True),
        sa.Column("currency", sa.Text(), server_default=sa.text("'RUB'"), nullable=False),
        sa.Column("unit_raw", sa.Text(), nullable=True),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "parsed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["source_product_id"],
            ["source_products.id"],
            name=op.f("fk_price_snapshots_source_product_id_source_products"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_price_snapshots")),
    )
    op.create_index("ix_price_snapshots_parsed_at", "price_snapshots", ["parsed_at"], unique=False)
    op.create_index(
        "ix_price_snapshots_source_product_id_parsed_at",
        "price_snapshots",
        ["source_product_id", "parsed_at"],
        unique=False,
    )

    op.create_table(
        "scrape_runs",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("shop_id", sa.BigInteger(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("items_seen", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("items_saved", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["shop_id"], ["shops.id"], name=op.f("fk_scrape_runs_shop_id_shops")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scrape_runs")),
    )
    op.create_index(
        "ix_scrape_runs_shop_id_started_at", "scrape_runs", ["shop_id", "started_at"], unique=False
    )
    op.create_index(
        "ix_scrape_runs_source_started_at", "scrape_runs", ["source", "started_at"], unique=False
    )
    op.create_index("ix_scrape_runs_status", "scrape_runs", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_scrape_runs_status", table_name="scrape_runs")
    op.drop_index("ix_scrape_runs_source_started_at", table_name="scrape_runs")
    op.drop_index("ix_scrape_runs_shop_id_started_at", table_name="scrape_runs")
    op.drop_table("scrape_runs")

    op.drop_index("ix_price_snapshots_source_product_id_parsed_at", table_name="price_snapshots")
    op.drop_index("ix_price_snapshots_parsed_at", table_name="price_snapshots")
    op.drop_table("price_snapshots")

    op.drop_index("uq_source_products_source_shop_source_product_id", table_name="source_products")
    op.drop_index("uq_source_products_source_shop_fingerprint", table_name="source_products")
    op.drop_index("ix_source_products_shop_id", table_name="source_products")
    op.drop_index("ix_source_products_normalized_title", table_name="source_products")
    op.drop_index("ix_source_products_last_seen_at", table_name="source_products")
    op.drop_index("ix_source_products_category_id", table_name="source_products")
    op.drop_table("source_products")

    op.drop_index("ix_categories_parent_id", table_name="categories")
    op.drop_table("categories")

    op.drop_index("ix_shops_scrape_status", table_name="shops")
    op.drop_index("ix_shops_next_scrape_at", table_name="shops")
    op.drop_table("shops")
