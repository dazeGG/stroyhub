"""Add DB-level updated_at triggers for mutable tables.

Revision ID: 20260524_0009
Revises: 20260524_0008
Create Date: 2026-05-24 00:00:00
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260524_0009"
down_revision: str | Sequence[str] | None = "20260524_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES_WITH_UPDATED_AT: tuple[str, ...] = (
    "shops",
    "shop_identities",
    "shop_source_candidates",
    "categories",
    "source_products",
    "category_overrides",
    "canonical_products",
)


def _trigger_name(table_name: str) -> str:
    return f"trg_{table_name}_set_updated_at"


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION set_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    for table_name in TABLES_WITH_UPDATED_AT:
        trigger_name = _trigger_name(table_name)
        op.execute(f"DROP TRIGGER IF EXISTS {trigger_name} ON {table_name};")
        op.execute(
            f"""
            CREATE TRIGGER {trigger_name}
            BEFORE UPDATE ON {table_name}
            FOR EACH ROW
            EXECUTE FUNCTION set_updated_at();
            """
        )


def downgrade() -> None:
    for table_name in reversed(TABLES_WITH_UPDATED_AT):
        trigger_name = _trigger_name(table_name)
        op.execute(f"DROP TRIGGER IF EXISTS {trigger_name} ON {table_name};")

    op.execute("DROP FUNCTION IF EXISTS set_updated_at();")
