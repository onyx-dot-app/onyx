"""remove default bot

Revision ID: 6d562f86c78b
Revises: 177de57c21c9
Create Date: 2024-11-22 11:51:29.331336

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "6d562f86c78b"
down_revision = "177de57c21c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            DELETE FROM slack_bot
            WHERE name = 'Default Bot'
            AND bot_token = ''
            AND app_token = ''
            AND NOT EXISTS (
                SELECT 1 FROM slack_channel_config
                WHERE slack_channel_config.slack_bot_id = slack_bot.id
            )
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            INSERT INTO slack_bot (name, enabled, bot_token, app_token)
            SELECT 'Default Bot', true, '', ''
            WHERE NOT EXISTS (SELECT 1 FROM slack_bot)
            RETURNING id;
            """
        )
    )
