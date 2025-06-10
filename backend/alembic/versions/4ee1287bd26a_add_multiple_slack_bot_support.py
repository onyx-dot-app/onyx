"""add_multiple_slack_bot_support

Revision ID: 4ee1287bd26a
Revises: 47e5bef3a1d7
Create Date: 2024-11-06 13:15:53.302644

"""

from typing import cast
from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session
from onyx.key_value_store.factory import get_kv_store
from onyx.db.models import SlackBot
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "4ee1287bd26a"
down_revision = "47e5bef3a1d7"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    # Create new slack_bot table
    op.create_table(
        "slack_bot",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("bot_token", sa.LargeBinary(), nullable=False),
        sa.Column("app_token", sa.LargeBinary(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("bot_token"),
        sa.UniqueConstraint("app_token"),
    )

    # # Create new slack_channel_config table
    op.create_table(
        "slack_channel_config",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("slack_bot_id", sa.Integer(), nullable=True),
        sa.Column("persona_id", sa.Integer(), nullable=True),
        sa.Column("channel_config", postgresql.JSONB(), nullable=False),
        sa.Column("response_type", sa.String(), nullable=False),
        sa.Column(
            "enable_auto_filters", sa.Boolean(), nullable=False, server_default="false"
        ),
        sa.ForeignKeyConstraint(
            ["slack_bot_id"],
            ["slack_bot.id"],
        ),
        sa.ForeignKeyConstraint(
            ["persona_id"],
            ["persona.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # Handle existing Slack bot tokens first
    bot_token = None
    app_token = None
    first_row_id = None

    try:
        tokens = cast(dict, get_kv_store().load("slack_bot_tokens_config_key"))
    except Exception:
        tokens = {}

    bot_token = tokens.get("bot_token")
    app_token = tokens.get("app_token")

    if bot_token and app_token:
        session = Session(bind=op.get_bind())
        new_slack_bot = SlackBot(
            name="Slack Bot (Migrated)",
            enabled=True,
            bot_token=bot_token,
            app_token=app_token,
        )
        session.add(new_slack_bot)
        session.commit()
        first_row_id = new_slack_bot.id

    # Create a default bot if none exists
    # This is in case there are no slack tokens but there are channels configured
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

    # Get the bot ID to use (either from existing migration or newly created)
    bot_id_query = sa.text(
        """
        SELECT COALESCE(
            :first_row_id,
            (SELECT id FROM slack_bot ORDER BY id ASC LIMIT 1)
        ) as bot_id;
        """
    )
    result = op.get_bind().execute(bot_id_query, {"first_row_id": first_row_id})
    bot_id = result.scalar()

    # CTE (Common Table Expression) that transforms the old slack_bot_config table data
    # This splits up the channel_names into their own rows
    channel_names_cte = """
        WITH channel_names AS (
            SELECT
                sbc.id as config_id,
                sbc.persona_id,
                sbc.response_type,
                sbc.enable_auto_filters,
                jsonb_array_elements_text(sbc.channel_config->'channel_names') as channel_name,
                sbc.channel_config->>'respond_tag_only' as respond_tag_only,
                sbc.channel_config->>'respond_to_bots' as respond_to_bots,
                sbc.channel_config->'respond_member_group_list' as respond_member_group_list,
                sbc.channel_config->'answer_filters' as answer_filters,
                sbc.channel_config->'follow_up_tags' as follow_up_tags
            FROM slack_bot_config sbc
        )
    """

    # Insert the channel names into the new slack_channel_config table
    insert_statement = """
        INSERT INTO slack_channel_config (
            slack_bot_id,
            persona_id,
            channel_config,
            response_type,
            enable_auto_filters
        )
        SELECT
            :bot_id,
            channel_name.persona_id,
            jsonb_build_object(
                'channel_name', channel_name.channel_name,
                'respond_tag_only',
                COALESCE((channel_name.respond_tag_only)::boolean, false),
                'respond_to_bots',
                COALESCE((channel_name.respond_to_bots)::boolean, false),
                'respond_member_group_list',
                COALESCE(channel_name.respond_member_group_list, '[]'::jsonb),
                'answer_filters',
                COALESCE(channel_name.answer_filters, '[]'::jsonb),
                'follow_up_tags',
                COALESCE(channel_name.follow_up_tags, '[]'::jsonb)
            ),
            channel_name.response_type,
            channel_name.enable_auto_filters
        FROM channel_names channel_name;
    """

    op.execute(sa.text(channel_names_cte + insert_statement).bindparams(bot_id=bot_id))

    # Clean up old tokens if they existed
    try:
        if bot_token and app_token:
            get_kv_store().delete("slack_bot_tokens_config_key")
    except Exception:
        pass
    # Rename the table
    op.rename_table(
        "slack_bot_config__standard_answer_category",
        "slack_channel_config__standard_answer_category",
    )

    # Rename the column
    op.alter_column(
        "slack_channel_config__standard_answer_category",
        "slack_bot_config_id",
        new_column_name="slack_channel_config_id",
    )

    # Drop the table with CASCADE to handle dependent objects
    op.execute("DROP TABLE slack_bot_config CASCADE")


def downgrade() -> None:
    # Recreate the old slack_bot_config table
    op.create_table(
        "slack_bot_config",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("persona_id", sa.Integer(), nullable=True),
        sa.Column("channel_config", postgresql.JSONB(), nullable=False),
        sa.Column("response_type", sa.String(), nullable=False),
        sa.Column("enable_auto_filters", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["persona_id"],
            ["persona.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # Migrate data back to the old format
    # Group by persona_id to combine channel names back into arrays
    op.execute(
        sa.text(
            """
            INSERT INTO slack_bot_config (
                persona_id,
                channel_config,
                response_type,
                enable_auto_filters
            )
            SELECT DISTINCT ON (persona_id)
                persona_id,
                jsonb_build_object(
                    'channel_names', (
                        SELECT jsonb_agg(c.channel_config->>'channel_name')
                        FROM slack_channel_config c
                        WHERE c.persona_id = scc.persona_id
                    ),
                    'respond_tag_only', (channel_config->>'respond_tag_only')::boolean,
                    'respond_to_bots', (channel_config->>'respond_to_bots')::boolean,
                    'respond_member_group_list', channel_config->'respond_member_group_list',
                    'answer_filters', channel_config->'answer_filters',
                    'follow_up_tags', channel_config->'follow_up_tags'
                ),
                response_type,
                enable_auto_filters
            FROM slack_channel_config scc
            WHERE persona_id IS NOT NULL;
            """
        )
    )

    # Rename the table back
    op.rename_table(
        "slack_channel_config__standard_answer_category",
        "slack_bot_config__standard_answer_category",
    )

    # Rename the column back
    op.alter_column(
        "slack_bot_config__standard_answer_category",
        "slack_channel_config_id",
        new_column_name="slack_bot_config_id",
    )

    # Try to save the first bot's tokens back to KV store
    try:
        first_bot = (
            op.get_bind()
            .execute(
                sa.text(
                    "SELECT bot_token, app_token FROM slack_bot ORDER BY id LIMIT 1"
                )
            )
            .first()
        )
        if first_bot and first_bot.bot_token and first_bot.app_token:
            tokens = {
                "bot_token": first_bot.bot_token,
                "app_token": first_bot.app_token,
            }
            get_kv_store().store("slack_bot_tokens_config_key", tokens)
    except Exception:
        pass

    # Drop the new tables in reverse order
    op.drop_table("slack_channel_config")
    op.drop_table("slack_bot")
