"""Widen source columns for Jira Service Management.

Revision ID: d5a7b3c9f206
Revises: ac05f4a21dbd
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d5a7b3c9f206"
down_revision: str | None = "ac05f4a21dbd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SOURCE_TABLES = (
    "hierarchy_node",
    "tag",
    "connector",
    "credential",
    "credential_capability_report",
)


def upgrade() -> None:
    for table_name in SOURCE_TABLES:
        op.alter_column(
            table_name,
            "source",
            existing_type=sa.String(length=20),
            type_=sa.String(length=50),
        )


def downgrade() -> None:
    # Keep the wider columns. A Jira Service Management source value may already
    # be stored, and shrinking would make the downgrade fail or truncate data.
    pass
