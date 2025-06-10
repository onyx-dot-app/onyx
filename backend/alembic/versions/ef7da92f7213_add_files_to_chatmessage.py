"""Add files to ChatMessage

Revision ID: ef7da92f7213
Revises: 401c1ac29467
Create Date: 2024-04-28 16:59:33.199153

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "ef7da92f7213"
down_revision = "401c1ac29467"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "chat_message",
        sa.Column("files", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("chat_message", "files")
