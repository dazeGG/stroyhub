"""add shop identities

Revision ID: 20260522_0005
Revises: fe917260ca58
Create Date: 2026-05-22 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260522_0005"
down_revision: str | None = "fe917260ca58"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "shop_identities",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("website_url", sa.Text(), nullable=True),
        sa.Column("preferred_source", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'active'"), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("locked_fields", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
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
            "status IN ('active', 'hold', 'disabled', 'out_of_scope')",
            name="ck_shop_identities_status_known",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shop_identities")),
    )
    op.create_index(
        "ix_shop_identities_preferred_source",
        "shop_identities",
        ["preferred_source"],
        unique=False,
    )
    op.create_index("ix_shop_identities_status", "shop_identities", ["status"], unique=False)

    op.add_column("shops", sa.Column("shop_identity_id", sa.BigInteger(), nullable=True))
    op.add_column("shops", sa.Column("source_type", sa.Text(), nullable=True))
    op.execute(
        """
        UPDATE shops
        SET source_type = CASE
            WHEN source = '2gis' THEN '2gis'
            WHEN source = 'unicom' THEN 'official_api'
            ELSE 'official_html'
        END
        """
    )
    op.alter_column("shops", "source_type", nullable=False)
    op.create_foreign_key(
        op.f("fk_shops_shop_identity_id_shop_identities"),
        "shops",
        "shop_identities",
        ["shop_identity_id"],
        ["id"],
    )
    op.create_check_constraint(
        "ck_shops_source_type_known",
        "shops",
        "source_type IN ('2gis', 'official_api', 'official_html')",
    )
    op.create_index("ix_shops_shop_identity_id", "shops", ["shop_identity_id"], unique=False)
    op.create_index("ix_shops_source_type", "shops", ["source_type"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_shops_source_type", table_name="shops")
    op.drop_index("ix_shops_shop_identity_id", table_name="shops")
    op.drop_constraint("ck_shops_source_type_known", "shops", type_="check")
    op.drop_constraint(
        op.f("fk_shops_shop_identity_id_shop_identities"),
        "shops",
        type_="foreignkey",
    )
    op.drop_column("shops", "source_type")
    op.drop_column("shops", "shop_identity_id")

    op.drop_index("ix_shop_identities_status", table_name="shop_identities")
    op.drop_index("ix_shop_identities_preferred_source", table_name="shop_identities")
    op.drop_table("shop_identities")
