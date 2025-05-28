"""Slack Followup

Revision ID: 7f726bad5367
Revises: 79acd316403a
Create Date: 2024-01-15 00:19:55.991224

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "7f726bad5367"
down_revision = "79acd316403a"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "chat_feedback",
        sa.Column("required_followup", sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("chat_feedback", "required_followup")
