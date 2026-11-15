"""Store resumable response checkpoints.

Revision ID: 6b4e821c0a93
Revises: 7a03b6e90c12
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "6b4e821c0a93"
down_revision = "7a03b6e90c12"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_response_checkpoint",
        sa.Column(
            "chat_message_id",
            sa.Integer(),
            sa.ForeignKey("chat_message.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "ownership_version", sa.BigInteger(), server_default="0", nullable=False
        ),
        sa.Column("state", postgresql.JSONB(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("chat_response_checkpoint")
