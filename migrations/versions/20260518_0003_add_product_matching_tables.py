"""add product matching tables

Revision ID: 20260518_0003
Revises: 20260517_0002
Create Date: 2026-05-18 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260518_0003"
down_revision: str | None = "20260517_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "canonical_products",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("category_id", sa.BigInteger(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("normalized_title", sa.Text(), nullable=False),
        sa.Column("brand", sa.Text(), nullable=True),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("unit_raw", sa.Text(), nullable=True),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("match_status", sa.Text(), server_default=sa.text("'active'"), nullable=False),
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
            name=op.f("fk_canonical_products_category_id_categories"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_canonical_products")),
    )
    op.create_index(
        "ix_canonical_products_category_id",
        "canonical_products",
        ["category_id"],
        unique=False,
    )
    op.create_index(
        "ix_canonical_products_normalized_title",
        "canonical_products",
        ["normalized_title"],
        unique=False,
    )

    op.create_table(
        "product_matches",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("canonical_product_id", sa.BigInteger(), nullable=False),
        sa.Column("source_product_id", sa.BigInteger(), nullable=False),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column(
            "matched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", sa.Text(), nullable=True),
        sa.Column("reason", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["canonical_product_id"],
            ["canonical_products.id"],
            name=op.f("fk_product_matches_canonical_product_id_canonical_products"),
        ),
        sa.ForeignKeyConstraint(
            ["source_product_id"],
            ["source_products.id"],
            name=op.f("fk_product_matches_source_product_id_source_products"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product_matches")),
    )
    op.create_index(
        "ix_product_matches_canonical_product_id",
        "product_matches",
        ["canonical_product_id"],
        unique=False,
    )
    op.create_index(
        "ix_product_matches_source_product_id",
        "product_matches",
        ["source_product_id"],
        unique=False,
    )
    op.create_index(
        "ix_product_matches_status_confidence",
        "product_matches",
        ["status", "confidence"],
        unique=False,
    )
    op.create_index(
        "uq_product_matches_source_product_accepted",
        "product_matches",
        ["source_product_id"],
        unique=True,
        postgresql_where=sa.text("status = 'accepted'"),
    )


def downgrade() -> None:
    op.drop_index("uq_product_matches_source_product_accepted", table_name="product_matches")
    op.drop_index("ix_product_matches_status_confidence", table_name="product_matches")
    op.drop_index("ix_product_matches_source_product_id", table_name="product_matches")
    op.drop_index("ix_product_matches_canonical_product_id", table_name="product_matches")
    op.drop_table("product_matches")

    op.drop_index("ix_canonical_products_normalized_title", table_name="canonical_products")
    op.drop_index("ix_canonical_products_category_id", table_name="canonical_products")
    op.drop_table("canonical_products")
