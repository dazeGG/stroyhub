"""add operator decision history

Revision ID: 20260526_0011
Revises: 20260526_0010
Create Date: 2026-05-26 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260526_0011"
down_revision: str | Sequence[str] | None = "20260526_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "operator_decisions",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("decision_type", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.BigInteger(), nullable=True),
        sa.Column("source_product_id", sa.BigInteger(), nullable=True),
        sa.Column("canonical_product_id", sa.BigInteger(), nullable=True),
        sa.Column("product_match_id", sa.BigInteger(), nullable=True),
        sa.Column("category_id", sa.BigInteger(), nullable=True),
        sa.Column("actor", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("previous_state", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("new_state", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("alternatives", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "decided_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "LENGTH(BTRIM(decision_type)) > 0",
            name=op.f("ck_operator_decisions_decision_type_not_empty"),
        ),
        sa.CheckConstraint(
            "LENGTH(BTRIM(action)) > 0",
            name=op.f("ck_operator_decisions_action_not_empty"),
        ),
        sa.CheckConstraint(
            "LENGTH(BTRIM(entity_type)) > 0",
            name=op.f("ck_operator_decisions_entity_type_not_empty"),
        ),
        sa.ForeignKeyConstraint(
            ["canonical_product_id"],
            ["canonical_products.id"],
            name=op.f("fk_operator_decisions_canonical_product_id_canonical_products"),
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            name=op.f("fk_operator_decisions_category_id_categories"),
        ),
        sa.ForeignKeyConstraint(
            ["product_match_id"],
            ["product_matches.id"],
            name=op.f("fk_operator_decisions_product_match_id_product_matches"),
        ),
        sa.ForeignKeyConstraint(
            ["source_product_id"],
            ["source_products.id"],
            name=op.f("fk_operator_decisions_source_product_id_source_products"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_operator_decisions")),
    )
    op.create_index(
        "ix_operator_decisions_canonical_product_id",
        "operator_decisions",
        ["canonical_product_id"],
        unique=False,
    )
    op.create_index(
        "ix_operator_decisions_category_id",
        "operator_decisions",
        ["category_id"],
        unique=False,
    )
    op.create_index(
        "ix_operator_decisions_decided_at",
        "operator_decisions",
        ["decided_at"],
        unique=False,
    )
    op.create_index(
        "ix_operator_decisions_decision_type",
        "operator_decisions",
        ["decision_type"],
        unique=False,
    )
    op.create_index(
        "ix_operator_decisions_product_match_id",
        "operator_decisions",
        ["product_match_id"],
        unique=False,
    )
    op.create_index(
        "ix_operator_decisions_source_product_id",
        "operator_decisions",
        ["source_product_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_operator_decisions_source_product_id", table_name="operator_decisions")
    op.drop_index("ix_operator_decisions_product_match_id", table_name="operator_decisions")
    op.drop_index("ix_operator_decisions_decision_type", table_name="operator_decisions")
    op.drop_index("ix_operator_decisions_decided_at", table_name="operator_decisions")
    op.drop_index("ix_operator_decisions_category_id", table_name="operator_decisions")
    op.drop_index("ix_operator_decisions_canonical_product_id", table_name="operator_decisions")
    op.drop_table("operator_decisions")
