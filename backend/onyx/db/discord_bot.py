"""CRUD operations for Discord bot models."""

from datetime import datetime
from datetime import timezone
from uuid import UUID

from sqlalchemy import delete
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from sqlalchemy.orm import Session

from onyx.db.models import DiscordBotConfig
from onyx.db.models import DiscordChannelConfig
from onyx.db.models import DiscordGuildConfig


# === DiscordBotConfig ===


def get_discord_bot_config(db_session: Session) -> DiscordBotConfig | None:
    """Get the Discord bot config for this tenant (at most one)."""
    return db_session.scalar(select(DiscordBotConfig).limit(1))


def create_discord_bot_config(
    db_session: Session,
    bot_token: str,
) -> DiscordBotConfig:
    """Create the Discord bot config. Raises if already exists."""
    existing = get_discord_bot_config(db_session)
    if existing:
        raise ValueError("Discord bot config already exists")

    config = DiscordBotConfig(bot_token=bot_token)
    db_session.add(config)
    db_session.flush()
    return config


def delete_discord_bot_config(db_session: Session) -> bool:
    """Delete the Discord bot config. Returns True if deleted."""
    result = db_session.execute(delete(DiscordBotConfig))
    db_session.flush()
    return result.rowcount > 0


# === DiscordGuildConfig ===


def get_discord_guild_configs(
    db_session: Session,
    include_channels: bool = False,
) -> list[DiscordGuildConfig]:
    """Get all guild configs for this tenant."""
    stmt = select(DiscordGuildConfig)
    if include_channels:
        stmt = stmt.options(joinedload(DiscordGuildConfig.channels))
    return list(db_session.scalars(stmt).unique().all())


def get_discord_guild_config_by_id(
    db_session: Session,
    config_id: UUID,
    include_channels: bool = False,
) -> DiscordGuildConfig | None:
    """Get a specific guild config by its UUID."""
    stmt = select(DiscordGuildConfig).where(DiscordGuildConfig.id == config_id)
    if include_channels:
        stmt = stmt.options(joinedload(DiscordGuildConfig.channels))
    return db_session.scalar(stmt)


def create_discord_guild_config(
    db_session: Session,
    registration_key: str,
) -> DiscordGuildConfig:
    """Create a new guild config with a registration key (guild_id=NULL)."""
    config = DiscordGuildConfig(registration_key=registration_key)
    db_session.add(config)
    db_session.flush()
    return config


def register_discord_guild(
    db_session: Session,
    config: DiscordGuildConfig,
    guild_id: int,
    guild_name: str,
) -> DiscordGuildConfig:
    """Complete registration by setting guild_id and guild_name."""
    config.guild_id = guild_id
    config.guild_name = guild_name
    config.registered_at = datetime.now(timezone.utc)
    db_session.flush()
    return config


def update_discord_guild_config(
    db_session: Session,
    config: DiscordGuildConfig,
    enabled: bool | None = None,
    respond_in_all_public_channels: bool | None = None,
    default_persona_id: int | None = None,
) -> DiscordGuildConfig:
    """Update guild config fields."""
    if enabled is not None:
        config.enabled = enabled
    if respond_in_all_public_channels is not None:
        config.respond_in_all_public_channels = respond_in_all_public_channels
    if default_persona_id is not None:
        config.default_persona_id = default_persona_id
    db_session.flush()
    return config


def delete_discord_guild_config(
    db_session: Session,
    config_id: UUID,
) -> bool:
    """Delete guild config (cascades to channel configs). Returns True if deleted."""
    result = db_session.execute(
        delete(DiscordGuildConfig).where(DiscordGuildConfig.id == config_id)
    )
    db_session.flush()
    return result.rowcount > 0


# === DiscordChannelConfig ===


def get_discord_channel_configs(
    db_session: Session,
    guild_config_id: UUID,
) -> list[DiscordChannelConfig]:
    """Get all channel configs for a guild."""
    return list(
        db_session.scalars(
            select(DiscordChannelConfig).where(
                DiscordChannelConfig.guild_config_id == guild_config_id
            )
        ).all()
    )


def get_discord_channel_config(
    db_session: Session,
    guild_config_id: UUID,
    channel_id: int,
) -> DiscordChannelConfig | None:
    """Get a specific channel config."""
    return db_session.scalar(
        select(DiscordChannelConfig).where(
            DiscordChannelConfig.guild_config_id == guild_config_id,
            DiscordChannelConfig.channel_id == channel_id,
        )
    )


def create_discord_channel_config(
    db_session: Session,
    guild_config_id: UUID,
    channel_id: int,
    channel_name: str,
    require_bot_invocation: bool = True,
    persona_override_id: int | None = None,
) -> DiscordChannelConfig:
    """Create a new channel config (whitelist a channel)."""
    config = DiscordChannelConfig(
        guild_config_id=guild_config_id,
        channel_id=channel_id,
        channel_name=channel_name,
        require_bot_invocation=require_bot_invocation,
        persona_override_id=persona_override_id,
    )
    db_session.add(config)
    db_session.flush()
    return config


def update_discord_channel_config(
    db_session: Session,
    config: DiscordChannelConfig,
    channel_name: str | None = None,
    require_bot_invocation: bool | None = None,
    persona_override_id: int | None = None,
    enabled: bool | None = None,
) -> DiscordChannelConfig:
    """Update channel config fields."""
    if channel_name is not None:
        config.channel_name = channel_name
    if require_bot_invocation is not None:
        config.require_bot_invocation = require_bot_invocation
    if persona_override_id is not None:
        config.persona_override_id = persona_override_id
    if enabled is not None:
        config.enabled = enabled
    db_session.flush()
    return config


def delete_discord_channel_config(
    db_session: Session,
    guild_config_id: UUID,
    channel_id: int,
) -> bool:
    """Delete a channel config. Returns True if deleted."""
    result = db_session.execute(
        delete(DiscordChannelConfig).where(
            DiscordChannelConfig.guild_config_id == guild_config_id,
            DiscordChannelConfig.channel_id == channel_id,
        )
    )
    db_session.flush()
    return result.rowcount > 0
