"""add search_settings use_port_flow

Revision ID: 81c4872d9666
Revises: d49e41659191
Create Date: 2026-06-03 12:11:18.288792

Additive: the per-SearchSettings reindex "port" flow gate. Default false, so
existing FUTUREs keep the legacy connector-rerun reindex.
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


def downgrade() -> None:
    op.drop_column("search_settings", "use_port_flow")
