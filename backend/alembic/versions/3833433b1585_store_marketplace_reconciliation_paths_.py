"""Store marketplace reconciliation paths and blocks.

Revision ID: 3833433b1585
Revises: a1420ed69215
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "3833433b1585"
down_revision = "a1420ed69215"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("skill", sa.Column("marketplace_path", sa.String(), nullable=True))
    op.add_column(
        "marketplace",
        sa.Column(
            "blocked_entries",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("marketplace", "blocked_entries")
    op.drop_column("skill", "marketplace_path")
