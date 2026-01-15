"""Add Discord bot tables

Revision ID: 8b5ce697290e
Revises: d1b637d7050a
Create Date: 2025-01-14

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "8b5ce697290e"
down_revision = "d1b637d7050a"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    # DiscordBotConfig
    op.create_table(
        "discord_bot_config",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("bot_token", sa.LargeBinary(), nullable=False),  # EncryptedString
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # DiscordGuildConfig
    op.create_table(
        "discord_guild_config",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("guild_id", sa.BigInteger(), nullable=True, unique=True),
        sa.Column("guild_name", sa.String(), nullable=True),
        sa.Column("registration_key", sa.String(), nullable=False, unique=True),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "respond_in_all_public_channels",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
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
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "guild_config_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("discord_guild_config.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("channel_name", sa.String(), nullable=False),
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
            "enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False
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
