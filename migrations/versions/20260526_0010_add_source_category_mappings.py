"""add source category mappings

Revision ID: 20260526_0010
Revises: 20260524_0009
Create Date: 2026-05-26 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260526_0010"
down_revision: str | Sequence[str] | None = "20260524_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "source_category_mappings",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("raw_category", sa.Text(), nullable=False),
        sa.Column("normalized_raw_category", sa.Text(), nullable=False),
        sa.Column("category_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'active'"), nullable=False),
        sa.Column(
            "confidence",
            sa.Numeric(4, 3),
            server_default=sa.text("1.000"),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Text(), nullable=True),
        sa.Column("updated_by", sa.Text(), nullable=True),
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
        sa.CheckConstraint(
            "status IN ('active', 'non_product', 'disabled')",
            name=op.f("ck_source_category_mappings_status_known"),
        ),
        sa.CheckConstraint(
            "(status = 'active' AND category_id IS NOT NULL) OR "
            "(status <> 'active' AND category_id IS NULL)",
            name=op.f("ck_source_category_mappings_status_category_consistent"),
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name=op.f("ck_source_category_mappings_confidence_range"),
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            name=op.f("fk_source_category_mappings_category_id_categories"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_category_mappings")),
        sa.UniqueConstraint(
            "source",
            "normalized_raw_category",
            name=op.f(
                "uq_source_category_mappings_source_normalized_raw_category"
            ),
        ),
    )
    op.create_index(
        "ix_source_category_mappings_category_id",
        "source_category_mappings",
        ["category_id"],
        unique=False,
    )
    op.create_index(
        "ix_source_category_mappings_source",
        "source_category_mappings",
        ["source"],
        unique=False,
    )
    op.create_index(
        "ix_source_category_mappings_status",
        "source_category_mappings",
        ["status"],
        unique=False,
    )
    op.execute(
        """
        CREATE TRIGGER trg_source_category_mappings_set_updated_at
        BEFORE UPDATE ON source_category_mappings
        FOR EACH ROW
        EXECUTE FUNCTION set_updated_at();
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_source_category_mappings_set_updated_at "
        "ON source_category_mappings;"
    )
    op.drop_index("ix_source_category_mappings_status", table_name="source_category_mappings")
    op.drop_index("ix_source_category_mappings_source", table_name="source_category_mappings")
    op.drop_index(
        "ix_source_category_mappings_category_id",
        table_name="source_category_mappings",
    )
    op.drop_table("source_category_mappings")
