"""add_chat_compression_fields

Revision ID: 90b409d06e50
Revises: 41fa44bef321
Create Date: 2026-01-26 09:13:09.635427

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "90b409d06e50"
down_revision = "41fa44bef321"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add summary_message_id to chat_session
    op.add_column(
        "chat_session",
        sa.Column(
            "summary_message_id",
            sa.Integer(),
            sa.ForeignKey("chat_message.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    # Add last_summarized_message_id to chat_message
    op.add_column(
        "chat_message",
        sa.Column(
            "last_summarized_message_id",
            sa.Integer(),
            sa.ForeignKey("chat_message.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("chat_message", "last_summarized_message_id")
    op.drop_column("chat_session", "summary_message_id")
