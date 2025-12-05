"""add multi-modal response support to chat_message

Revision ID: 34ef1e82a4fa
Revises: e8f0d2a38171
Create Date: 2025-12-04 14:53:05.821715

"""

from alembic import op
import sqlalchemy as sa

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


def downgrade() -> None:
    # Drop the columns in reverse order
    op.drop_column("chat_message", "model_name")
    op.drop_column("chat_message", "model_provider")
