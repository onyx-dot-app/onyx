"""Add canonical agent output to chat responses.

Revision ID: 7a03b6e90c12
Revises: ad99acb9be41
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "7a03b6e90c12"
down_revision = "ad99acb9be41"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chat_message", sa.Column("agent_transcript", postgresql.JSONB(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("chat_message", "agent_transcript")
