"""add chat message request params

Revision ID: 06a38a307492
Revises: dd55634b8532
Create Date: 2026-08-19 10:15:51.474747

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "06a38a307492"
down_revision = "dd55634b8532"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chat_message",
        sa.Column("request_params", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("chat_message", "request_params")
