"""add shop source candidates

Revision ID: 20260523_0006
Revises: 20260522_0005
Create Date: 2026-05-23 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260523_0006"
down_revision: str | None = "20260522_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "shop_source_candidates",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("source_type", sa.Text(), server_default=sa.text("'2gis'"), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("website_url", sa.Text(), nullable=True),
        sa.Column("rubrics", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("has_products", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("has_prices", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("has_website", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("product_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "priced_product_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("priority", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("priority_reason", sa.Text(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("missing_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_shop_id", sa.BigInteger(), nullable=True),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
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
        sa.CheckConstraint("source = '2gis'", name="ck_shop_source_candidates_source_known"),
        sa.CheckConstraint(
            "status IN ('pending', 'stale', 'hidden', 'archived', 'approved')",
            name="ck_shop_source_candidates_status_known",
        ),
        sa.ForeignKeyConstraint(
            ["approved_shop_id"],
            ["shops.id"],
            name=op.f("fk_shop_source_candidates_approved_shop_id_shops"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shop_source_candidates")),
        sa.UniqueConstraint(
            "source",
            "source_id",
            name="uq_shop_source_candidates_source_source_id",
        ),
    )
    op.create_index(
        "ix_shop_source_candidates_last_seen_at",
        "shop_source_candidates",
        ["last_seen_at"],
        unique=False,
    )
    op.create_index(
        "ix_shop_source_candidates_priority",
        "shop_source_candidates",
        ["priority"],
        unique=False,
    )
    op.create_index(
        "ix_shop_source_candidates_status",
        "shop_source_candidates",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_shop_source_candidates_status", table_name="shop_source_candidates")
    op.drop_index("ix_shop_source_candidates_priority", table_name="shop_source_candidates")
    op.drop_index("ix_shop_source_candidates_last_seen_at", table_name="shop_source_candidates")
    op.drop_table("shop_source_candidates")
