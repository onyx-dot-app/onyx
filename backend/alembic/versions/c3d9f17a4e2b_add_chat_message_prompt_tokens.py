"""add chat_message.prompt_tokens

Revision ID: f1a2b3c4d5e6
Revises: 99ecd56cb2ce
Create Date: 2026-06-04 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "f1a2b3c4d5e6"
down_revision = "99ecd56cb2ce"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chat_message",
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("chat_message", "prompt_tokens")
