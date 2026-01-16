"""CRUD operations for Discord bot models."""

from datetime import datetime
from datetime import timezone

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


def get_guild_configs(
    db_session: Session,
    include_channels: bool = False,
) -> list[DiscordGuildConfig]:
    """Get all guild configs for this tenant."""
    stmt = select(DiscordGuildConfig)
    if include_channels:
        stmt = stmt.options(joinedload(DiscordGuildConfig.channels))
    return list(db_session.scalars(stmt).unique().all())


def get_guild_config_by_internal_id(
    db_session: Session,
    internal_id: int,
) -> DiscordGuildConfig | None:
    """Get a specific guild config by its ID."""
    return db_session.scalar(
        select(DiscordGuildConfig).where(DiscordGuildConfig.id == internal_id)
    )


def get_guild_config_by_discord_id(
    db_session: Session,
    guild_id: int,
) -> DiscordGuildConfig | None:
    """Get a guild config by Discord guild ID."""
    return db_session.scalar(
        select(DiscordGuildConfig).where(DiscordGuildConfig.guild_id == guild_id)
    )


def get_guild_config_by_registration_key(
    db_session: Session,
    registration_key: str,
) -> DiscordGuildConfig | None:
    """Get a guild config by its registration key."""
    return db_session.scalar(
        select(DiscordGuildConfig).where(
            DiscordGuildConfig.registration_key == registration_key
        )
    )


def create_guild_config(
    db_session: Session,
    registration_key: str,
) -> DiscordGuildConfig:
    """Create a new guild config with a registration key (guild_id=NULL)."""
    config = DiscordGuildConfig(registration_key=registration_key)
    db_session.add(config)
    db_session.flush()
    return config


def register_guild(
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


def update_guild_config(
    db_session: Session,
    config: DiscordGuildConfig,
    enabled: bool,
    default_persona_id: int,
) -> DiscordGuildConfig:
    """Update guild config fields."""
    config.enabled = enabled
    config.default_persona_id = default_persona_id
    db_session.flush()
    return config


def delete_guild_config(
    db_session: Session,
    internal_id: int,
) -> bool:
    """Delete guild config (cascades to channel configs). Returns True if deleted."""
    result = db_session.execute(
        delete(DiscordGuildConfig).where(DiscordGuildConfig.id == internal_id)
    )
    db_session.flush()
    return result.rowcount > 0


# === DiscordChannelConfig ===


def get_channel_configs(
    db_session: Session,
    guild_config_id: int,
) -> list[DiscordChannelConfig]:
    """Get all channel configs for a guild."""
    return list(
        db_session.scalars(
            select(DiscordChannelConfig).where(
                DiscordChannelConfig.guild_config_id == guild_config_id
            )
        ).all()
    )


def get_channel_config_by_discord_ids(
    db_session: Session,
    guild_id: int,
    channel_id: int,
) -> DiscordChannelConfig | None:
    """Get a specific channel config by guild_id and channel_id."""
    return db_session.scalar(
        select(DiscordChannelConfig)
        .join(DiscordGuildConfig)
        .where(
            DiscordGuildConfig.guild_id == guild_id,
            DiscordChannelConfig.channel_id == channel_id,
        )
    )


def get_channel_config_by_internal_ids(
    db_session: Session,
    guild_config_id: int,
    channel_config_id: int,
) -> DiscordChannelConfig | None:
    """Get a specific channel config by guild_config_id and channel_config_id"""
    return db_session.scalar(
        select(DiscordChannelConfig).where(
            DiscordChannelConfig.guild_config_id == guild_config_id,
            DiscordChannelConfig.id == channel_config_id,
        )
    )


def update_discord_channel_config(
    db_session: Session,
    config: DiscordChannelConfig,
    channel_name: str,
    thread_only_mode: bool,
    require_bot_invocation: bool,
    persona_override_id: int,
    enabled: bool,
) -> DiscordChannelConfig:
    """Update channel config fields."""
    config.channel_name = channel_name
    config.require_bot_invocation = require_bot_invocation
    config.persona_override_id = persona_override_id
    config.enabled = enabled
    config.thread_only_mode = thread_only_mode
    db_session.flush()
    return config


def delete_discord_channel_config(
    db_session: Session,
    guild_config_id: int,
    channel_config_id: int,
) -> bool:
    """Delete a channel config. Returns True if deleted."""
    result = db_session.execute(
        delete(DiscordChannelConfig).where(
            DiscordChannelConfig.guild_config_id == guild_config_id,
            DiscordChannelConfig.id == channel_config_id,
        )
    )
    db_session.flush()
    return result.rowcount > 0
