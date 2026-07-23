"""add chat session reasoning effort override

Revision ID: c2cc933f0a40
Revises: fe958f19e42b
Create Date: 2026-07-22 14:23:57.000000

"""

from alembic import op
import sqlalchemy as sa

revision = "c2cc933f0a40"
down_revision = "fe958f19e42b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chat_session",
        sa.Column("reasoning_effort_override", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("chat_session", "reasoning_effort_override")
