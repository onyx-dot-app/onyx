"""Add opencode_session_id to build_session

Revision ID: 3fa4f9869b2d
Revises: 19c0ccb01687
Create Date: 2026-02-17 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "3fa4f9869b2d"
down_revision = "19c0ccb01687"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "build_session",
        sa.Column("opencode_session_id", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("build_session", "opencode_session_id")
