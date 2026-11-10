"""Add marketplace Skill limit blocks

Revision ID: a604d04ad21b
Revises: e3241e0833c0
Create Date: 2026-11-08 11:30:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "a604d04ad21b"
down_revision = "e3241e0833c0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "marketplace",
        sa.Column(
            "skill_limit_blocks",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("marketplace", "skill_limit_blocks")
