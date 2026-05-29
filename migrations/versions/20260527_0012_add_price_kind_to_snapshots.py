"""add price kind to price snapshots

Revision ID: 20260527_0012
Revises: 20260526_0011
Create Date: 2026-05-27 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260527_0012"
down_revision: str | Sequence[str] | None = "20260526_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "price_snapshots",
        sa.Column(
            "price_kind",
            sa.Text(),
            server_default=sa.text("'exact'"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        op.f("ck_price_snapshots_price_kind_known"),
        "price_snapshots",
        "price_kind IN ('exact', 'from', 'range', 'unknown')",
    )

    op.execute(
        """
        UPDATE price_snapshots
        SET price_kind = 'unknown'
        WHERE price IS NULL
        """
    )
    op.execute(
        """
        UPDATE price_snapshots
        SET price_kind = 'from'
        WHERE raw->'offer'->'price_value' ? 'from'
        """
    )
    op.execute(
        """
        UPDATE price_snapshots
        SET price_kind = 'from'
        WHERE price IS NOT NULL
          AND LOWER(raw->'offer'->>'price') ~ '(^|[[:space:]])от[[:space:]]*[0-9]'
        """
    )
    op.execute(
        """
        UPDATE price_snapshots AS snapshots
        SET price_kind = 'from'
        FROM source_products AS products
        WHERE snapshots.source_product_id = products.id
          AND snapshots.price IS NOT NULL
          AND LOWER(products.title) ~
              '^(арматура|брус|доска|лист|пиловочник|полоса|профиль|труба|уголок|фанера|швеллер)([[:space:][:punct:]]|$)'
          AND (
              LOWER(products.title) ~ '(^|[[:space:][:punct:]])от[[:space:]]*[0-9]'
              OR LOWER(products.title) ~
                  '(^|[[:space:][:punct:]])от.{0,120}(^|[[:space:][:punct:]])до'
              OR LOWER(products.title) ~
                  '(^|[[:space:][:punct:]])и[[:space:]]+более([[:space:][:punct:]]|$)'
          )
        """
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_price_snapshots_price_kind_known"),
        "price_snapshots",
        type_="check",
    )
    op.drop_column("price_snapshots", "price_kind")
