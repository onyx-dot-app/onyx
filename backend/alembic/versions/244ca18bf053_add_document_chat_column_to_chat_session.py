"""add document_chat column to chat_session

Revision ID: 244ca18bf053
Revises: a7688ab35c45
Create Date: 2025-06-10 14:51:01.416631

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "244ca18bf053"
down_revision = "a7688ab35c45"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add document_chat column to chat_session table
    op.add_column(
        "chat_session",
        sa.Column(
            "document_chat", sa.Boolean(), nullable=False, server_default="false"
        ),
    )


def downgrade() -> None:
    # Remove document_chat column from chat_session table
    op.drop_column("chat_session", "document_chat")
