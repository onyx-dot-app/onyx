"""add_user_oauth_token_to_slack_bot

Revision ID: b4ef3ae0bf6e
Revises: 505c488f6662
Create Date: 2025-08-26 17:47:41.788462

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b4ef3ae0bf6e"
down_revision = "505c488f6662"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add user_token column to slack_bot table
    op.add_column("slack_bot", sa.Column("user_token", sa.LargeBinary(), nullable=True))


def downgrade() -> None:
    # Remove user_token column from slack_bot table
    op.drop_column("slack_bot", "user_token")
