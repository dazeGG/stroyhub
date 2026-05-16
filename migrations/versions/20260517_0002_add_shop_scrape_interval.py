"""add shop scrape interval

Revision ID: 20260517_0002
Revises: 20260516_0001
Create Date: 2026-05-17 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260517_0002"
down_revision: str | None = "20260516_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "shops",
        sa.Column("scrape_interval", sa.Integer(), server_default=sa.text("86400"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("shops", "scrape_interval")
