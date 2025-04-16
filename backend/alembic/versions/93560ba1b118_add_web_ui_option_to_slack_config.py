"""add web ui option to slack config

Revision ID: 93560ba1b118
Revises: 6d562f86c78b
Create Date: 2024-11-24 06:36:17.490612

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "93560ba1b118"
down_revision = "6d562f86c78b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add show_continue_in_web_ui with default False to all existing channel_configs
    op.execute(
        """
        UPDATE slack_channel_config
        SET channel_config = channel_config || '{"show_continue_in_web_ui": false}'::jsonb
        WHERE NOT channel_config ? 'show_continue_in_web_ui'
        """
    )


def downgrade() -> None:
    # Remove show_continue_in_web_ui from all channel_configs
    op.execute(
        """
        UPDATE slack_channel_config
        SET channel_config = channel_config - 'show_continue_in_web_ui'
        """
    )
