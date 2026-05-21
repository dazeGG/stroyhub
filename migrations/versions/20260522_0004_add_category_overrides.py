"""add category overrides

Revision ID: 20260522_0004
Revises: 20260518_0003
Create Date: 2026-05-22 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260522_0004"
down_revision: str | None = "20260518_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "category_overrides",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("source_product_id", sa.BigInteger(), nullable=False),
        sa.Column("category_id", sa.BigInteger(), nullable=False),
        sa.Column("previous_category_id", sa.BigInteger(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'active'"), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=True),
        sa.Column("updated_by", sa.Text(), nullable=True),
        sa.Column("deactivated_by", sa.Text(), nullable=True),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
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
            name=op.f("fk_category_overrides_category_id_categories"),
        ),
        sa.ForeignKeyConstraint(
            ["previous_category_id"],
            ["categories.id"],
            name=op.f("fk_category_overrides_previous_category_id_categories"),
        ),
        sa.ForeignKeyConstraint(
            ["source_product_id"],
            ["source_products.id"],
            name=op.f("fk_category_overrides_source_product_id_source_products"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_category_overrides")),
    )
    op.create_index(
        "ix_category_overrides_category_id",
        "category_overrides",
        ["category_id"],
        unique=False,
    )
    op.create_index(
        "ix_category_overrides_created_at",
        "category_overrides",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_category_overrides_status",
        "category_overrides",
        ["status"],
        unique=False,
    )
    op.create_index(
        "uq_category_overrides_source_product_active",
        "category_overrides",
        ["source_product_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_category_overrides_source_product_active",
        table_name="category_overrides",
    )
    op.drop_index("ix_category_overrides_status", table_name="category_overrides")
    op.drop_index("ix_category_overrides_created_at", table_name="category_overrides")
    op.drop_index("ix_category_overrides_category_id", table_name="category_overrides")
    op.drop_table("category_overrides")
