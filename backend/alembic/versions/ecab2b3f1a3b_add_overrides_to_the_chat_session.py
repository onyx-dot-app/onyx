"""Add overrides to the chat session

Revision ID: ecab2b3f1a3b
Revises: 38eda64af7fe
Create Date: 2024-04-01 19:08:21.359102

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "ecab2b3f1a3b"
down_revision = "38eda64af7fe"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "chat_session",
        sa.Column(
            "llm_override",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "chat_session",
        sa.Column(
            "prompt_override",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("chat_session", "prompt_override")
    op.drop_column("chat_session", "llm_override")
