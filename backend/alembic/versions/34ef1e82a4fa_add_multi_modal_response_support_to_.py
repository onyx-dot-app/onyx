"""add multi-modal response support to chat_message

Revision ID: 34ef1e82a4fa
Revises: e8f0d2a38171
Create Date: 2025-12-04 14:53:05.821715

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "34ef1e82a4fa"
down_revision = "e8f0d2a38171"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add model_provider column to track which LLM provider generated the response
    op.add_column(
        "chat_message",
        sa.Column("model_provider", sa.String(), nullable=True),
    )

    # Add model_name column to track which specific model generated the response
    op.add_column(
        "chat_message",
        sa.Column("model_name", sa.String(), nullable=True),
    )

    # Add response_group_id column to group parallel multi-model responses together.
    # When a user sends a message with multiple models selected, each model's response
    # shares the same response_group_id. This distinguishes them from alternative branches
    # (regenerations/edits) which have different response_group_ids or NULL.
    op.add_column(
        "chat_message",
        sa.Column("response_group_id", postgresql.UUID(as_uuid=True), nullable=True),
    )

    # Create a partial index for efficient grouping queries on response_group_id
    # Only index rows where response_group_id is not NULL (multi-model responses)
    op.create_index(
        "ix_chat_message_response_group_id",
        "chat_message",
        ["response_group_id"],
        postgresql_where=sa.text("response_group_id IS NOT NULL"),
    )


def downgrade() -> None:
    # Drop the index first
    op.drop_index("ix_chat_message_response_group_id", table_name="chat_message")

    # Drop the columns in reverse order
    op.drop_column("chat_message", "response_group_id")
    op.drop_column("chat_message", "model_name")
    op.drop_column("chat_message", "model_provider")
