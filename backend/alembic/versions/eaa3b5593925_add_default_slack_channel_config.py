"""add default slack channel config

Revision ID: eaa3b5593925
Revises: 98a5008d8711
Create Date: 2025-02-03 18:07:56.552526

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "eaa3b5593925"
down_revision = "98a5008d8711"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add is_default column
    op.add_column(
        "slack_channel_config",
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default="false"),
    )

    op.create_index(
        "ix_slack_channel_config_slack_bot_id_default",
        "slack_channel_config",
        ["slack_bot_id", "is_default"],
        unique=True,
        postgresql_where=sa.text("is_default IS TRUE"),
    )

    # Create default channel configs for existing slack bots without one
    conn = op.get_bind()
    slack_bots = conn.execute(sa.text("SELECT id FROM slack_bot")).fetchall()

    for slack_bot in slack_bots:
        slack_bot_id = slack_bot[0]
        existing_default = conn.execute(
            sa.text(
                "SELECT id FROM slack_channel_config WHERE slack_bot_id = :bot_id AND is_default = TRUE"
            ),
            {"bot_id": slack_bot_id},
        ).fetchone()

        if not existing_default:
            conn.execute(
                sa.text(
                    """
                    INSERT INTO slack_channel_config (
                        slack_bot_id, persona_id, channel_config, enable_auto_filters, is_default
                    ) VALUES (
                        :bot_id, NULL,
                        '{"channel_name": null, '
                        '"respond_member_group_list": [], '
                        '"answer_filters": [], '
                        '"follow_up_tags": [], '
                        '"respond_tag_only": true}',
                        FALSE, TRUE
                    )
                """
                ),
                {"bot_id": slack_bot_id},
            )


def downgrade() -> None:
    # Delete default slack channel configs
    conn = op.get_bind()
    conn.execute(sa.text("DELETE FROM slack_channel_config WHERE is_default = TRUE"))

    # Remove index
    op.drop_index(
        "ix_slack_channel_config_slack_bot_id_default",
        table_name="slack_channel_config",
    )

    # Remove is_default column
    op.drop_column("slack_channel_config", "is_default")
