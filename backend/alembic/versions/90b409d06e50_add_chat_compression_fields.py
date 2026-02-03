"""add_chat_compression_fields

Revision ID: 90b409d06e50
Revises: f220515df7b4
Create Date: 2026-01-26 09:13:09.635427

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "90b409d06e50"
down_revision = "f220515df7b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add last_summarized_message_id to chat_message
    # This field marks a message as a summary and indicates the last message it covers.
    # Summaries are branch-aware via their parent_message_id pointing to the branch.
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
