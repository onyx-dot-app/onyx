"""add chat_message.prompt_tokens

Revision ID: c3d9f17a4e2b
Revises: f3a9c1d4b7e2
Create Date: 2026-06-04 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "c3d9f17a4e2b"
down_revision = "f3a9c1d4b7e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chat_message",
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
    )
    # The producing model's context window, stored per turn so a reload after a
    # mid-chat model switch keeps the original gauge denominator.
    op.add_column(
        "chat_message",
        sa.Column("max_input_tokens", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("chat_message", "max_input_tokens")
    op.drop_column("chat_message", "prompt_tokens")
