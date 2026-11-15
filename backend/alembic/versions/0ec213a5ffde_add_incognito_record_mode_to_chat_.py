"""add incognito_record_mode to chat_session

Revision ID: 0ec213a5ffde
Revises: a44c4ebac3d6
Create Date: 2026-08-07 13:05:59.971436

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0ec213a5ffde"
down_revision = "a44c4ebac3d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Unbounded VARCHAR, as reasoning_effort_override on this table already
    # does, so adding a longer mode stays a code change.
    op.add_column(
        "chat_session",
        sa.Column("incognito_record_mode", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("chat_session", "incognito_record_mode")
