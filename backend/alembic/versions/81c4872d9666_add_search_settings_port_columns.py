"""add search_settings port columns

Revision ID: 81c4872d9666
Revises: d49e41659191
Create Date: 2026-06-03 12:11:18.288792

Additive port-flow columns on search_settings:
- use_port_flow: the per-SearchSettings reindex "port" flow gate. Default false,
  so existing FUTUREs keep the legacy connector-rerun reindex.
- port_backfill_source_id: the now-PAST index an INSTANT port-flow swap keeps
  backfilling from after promoting the FUTURE. Nullable self-FK; null for all
  existing settings.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "81c4872d9666"
down_revision = "d49e41659191"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "search_settings",
        sa.Column(
            "use_port_flow",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
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
    op.drop_column("search_settings", "use_port_flow")
