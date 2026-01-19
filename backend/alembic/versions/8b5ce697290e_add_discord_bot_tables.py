"""Add Discord bot tables

Revision ID: 8b5ce697290e
Revises: a1b2c3d4e5f7
Create Date: 2025-01-14

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "8b5ce697290e"
down_revision = "a1b2c3d4e5f7"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    # DiscordBotConfig (singleton table - one per tenant)
    op.create_table(
        "discord_bot_config",
        sa.Column(
            "id",
            sa.String(),
            primary_key=True,
            server_default=sa.text("'SINGLETON'"),
        ),
        sa.Column("bot_token", sa.LargeBinary(), nullable=False),  # EncryptedString
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("id = 'SINGLETON'", name="ck_discord_bot_config_singleton"),
    )

    # DiscordGuildConfig
    op.create_table(
        "discord_guild_config",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("guild_id", sa.BigInteger(), nullable=True, unique=True),
        sa.Column("guild_name", sa.String(), nullable=True),
        sa.Column("registration_key", sa.String(), nullable=False, unique=True),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "default_persona_id",
            sa.Integer(),
            sa.ForeignKey("persona.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
    )

    # DiscordChannelConfig
    op.create_table(
        "discord_channel_config",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "guild_config_id",
            sa.Integer(),
            sa.ForeignKey("discord_guild_config.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("channel_name", sa.String(), nullable=False),
        sa.Column(
            "channel_type",
            sa.String(20),
            server_default=sa.text("'text'"),
            nullable=False,
        ),
        sa.Column(
            "is_private",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "thread_only_mode",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "require_bot_invocation",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "persona_override_id",
            sa.Integer(),
            sa.ForeignKey("persona.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
    )

    # Unique constraint: one config per channel per guild
    op.create_unique_constraint(
        "uq_discord_channel_guild_channel",
        "discord_channel_config",
        ["guild_config_id", "channel_id"],
    )


def downgrade() -> None:
    op.drop_table("discord_channel_config")
    op.drop_table("discord_guild_config")
    op.drop_table("discord_bot_config")
