"""add research_answer_purpose to chat_message

Revision ID: f8a9b2c3d4e5
Revises: 5ae8240accb3
Create Date: 2025-01-27 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f8a9b2c3d4e5"
down_revision = "5ae8240accb3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add research_answer_purpose column to chat_message table
    op.add_column(
        "chat_message",
        sa.Column("research_answer_purpose", sa.String(), nullable=True),
    )


def downgrade() -> None:
    # Remove research_answer_purpose column from chat_message table
    op.drop_column("chat_message", "research_answer_purpose")
