"""non-nullbale slack bot id in channel config

Revision ID: f7a894b06d02
Revises: 9f696734098f
Create Date: 2024-12-06 12:55:42.845723

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f7a894b06d02"
down_revision = "9f696734098f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Delete all rows with null slack_bot_id
    op.execute("DELETE FROM slack_channel_config WHERE slack_bot_id IS NULL")

    # Make slack_bot_id non-nullable
    op.alter_column(
        "slack_channel_config",
        "slack_bot_id",
        existing_type=sa.Integer(),
        nullable=False,
    )


def downgrade() -> None:
    # Make slack_bot_id nullable again
    op.alter_column(
        "slack_channel_config",
        "slack_bot_id",
        existing_type=sa.Integer(),
        nullable=True,
    )
