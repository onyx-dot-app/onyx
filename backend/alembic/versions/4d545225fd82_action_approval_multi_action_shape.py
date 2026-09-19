"""action_approval multi-action shape

Replace the scalar ``action_type`` column with a structured ``actions``
JSONB list (one request can match multiple catalog actions, e.g.
batched GraphQL). Adds ``app_name`` so each row is self-contained.

Craft is beta — existing rows are wiped rather than backfilled.

Revision ID: 4d545225fd82
Revises: b4950827c0dd
Create Date: 2026-05-28 14:48:37.979772

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "4d545225fd82"
down_revision = "b4950827c0dd"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DELETE FROM action_approval")
    op.drop_column("action_approval", "action_type")
    op.add_column(
        "action_approval",
        sa.Column("actions", postgresql.JSONB(), nullable=False),
    )
    op.add_column(
        "action_approval",
        sa.Column("app_name", sa.String(), nullable=False),
    )


def downgrade() -> None:
    op.execute("DELETE FROM action_approval")
    op.drop_column("action_approval", "app_name")
    op.drop_column("action_approval", "actions")
    op.add_column(
        "action_approval",
        sa.Column("action_type", sa.String(), nullable=False),
    )
