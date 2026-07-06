"""add retention_exempt to chat_session

Revision ID: da41c7ca5933
Revises: 2e0b2b146de1
Create Date: 2026-07-06 23:09:25.146385

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "da41c7ca5933"
down_revision = "2e0b2b146de1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chat_session",
        sa.Column(
            "retention_exempt",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("chat_session", "retention_exempt")
