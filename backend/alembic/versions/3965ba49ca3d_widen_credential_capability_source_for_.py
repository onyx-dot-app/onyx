"""Widen credential capability report sources for Jira Service Management.

Revision ID: 3965ba49ca3d
Revises: c3e8a1f5d702
Create Date: 2026-11-06 22:21:39.861197

"""

from alembic import op
import sqlalchemy as sa

revision = "3965ba49ca3d"
down_revision = "c3e8a1f5d702"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Accommodate the 23-character JIRA_SERVICE_MANAGEMENT enum name."""
    op.alter_column(
        "credential_capability_report",
        "source",
        type_=sa.String(length=23),
        existing_type=sa.String(length=20),
        existing_nullable=False,
    )


def downgrade() -> None:
    """Retain the wider column so existing capability reports are not truncated."""
    # A wider VARCHAR is compatible with the previous schema. Shrinking it would
    # fail for persisted JSM reports; rewriting/deleting those reports loses data.
