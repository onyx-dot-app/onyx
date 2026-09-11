"""Widen capability report sources for Jira Service Management.

Revision ID: 62c62f2eac71
Revises: 287021f3b46c
"""

import sqlalchemy as sa
from alembic import op

revision = "62c62f2eac71"
down_revision = "287021f3b46c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "credential_capability_report", "source", type_=sa.String(length=50)
    )


def downgrade() -> None:
    # Keep the wider column to avoid truncating saved source names.
    pass
