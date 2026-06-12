"""add search_settings port_backfill_source_id

Revision ID: e7f3a9b2c1d4
Revises: 81c4872d9666
Create Date: 2026-06-11 12:00:00.000000

Additive: the now-PAST index an INSTANT port-flow swap keeps backfilling from
after promoting the FUTURE. Nullable self-FK; null for all existing settings.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "e7f3a9b2c1d4"
down_revision = "81c4872d9666"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "search_settings",
        sa.Column("port_backfill_source_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "search_settings_port_backfill_source_id_fkey",
        "search_settings",
        "search_settings",
        ["port_backfill_source_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "search_settings_port_backfill_source_id_fkey",
        "search_settings",
        type_="foreignkey",
    )
    op.drop_column("search_settings", "port_backfill_source_id")
