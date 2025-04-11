"""Combine Search and Chat

Revision ID: 9f696734098f
Revises: a8c2065484e6
Create Date: 2024-11-27 15:32:19.694972

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "9f696734098f"
down_revision = "a8c2065484e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("chat_session", "description", nullable=True)
    op.drop_column("chat_session", "one_shot")
    op.drop_column("slack_channel_config", "response_type")


def downgrade() -> None:
    op.execute("UPDATE chat_session SET description = '' WHERE description IS NULL")
    op.alter_column("chat_session", "description", nullable=False)
    op.add_column(
        "chat_session",
        sa.Column("one_shot", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "slack_channel_config",
        sa.Column(
            "response_type", sa.String(), nullable=False, server_default="citations"
        ),
    )
