"""CRUD operations for Discord bot models."""

from datetime import datetime
from datetime import timezone

from sqlalchemy import delete
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload
from sqlalchemy.orm import Session

from onyx.auth.api_key import build_displayable_api_key
from onyx.auth.api_key import generate_api_key
from onyx.auth.api_key import hash_api_key
from onyx.auth.schemas import UserRole
from onyx.configs.constants import DISCORD_SERVICE_API_KEY_NAME
from onyx.db.api_key import insert_api_key
from onyx.db.models import ApiKey
from onyx.db.models import DiscordBotConfig
from onyx.db.models import DiscordChannelConfig
from onyx.db.models import DiscordGuildConfig
from onyx.db.models import User
from onyx.db.utils import DiscordChannelView
from onyx.server.api_key.models import APIKeyArgs
from onyx.utils.logger import setup_logger

logger = setup_logger()


# === DiscordBotConfig ===


def get_discord_bot_config(db_session: Session) -> DiscordBotConfig | None:
    """Get the Discord bot config for this tenant (at most one)."""
    return db_session.scalar(select(DiscordBotConfig).limit(1))


def create_discord_bot_config(
    db_session: Session,
    bot_token: str,
) -> DiscordBotConfig:
    """Create the Discord bot config. Raises ValueError if already exists.

    The check constraint on id='SINGLETON' ensures only one config per tenant.
    """
    existing = get_discord_bot_config(db_session)
    if existing:
        raise ValueError("Discord bot config already exists")

    config = DiscordBotConfig(bot_token=bot_token)
    db_session.add(config)
    try:
        db_session.flush()
    except IntegrityError:
        # Race condition: another request created the config concurrently
        db_session.rollback()
        raise ValueError("Discord bot config already exists")
    return config


def delete_discord_bot_config(db_session: Session) -> bool:
    """Delete the Discord bot config. Returns True if deleted."""
    result = db_session.execute(delete(DiscordBotConfig))
    db_session.flush()
    return result.rowcount > 0  # type: ignore[attr-defined]


# === Discord Service API Key ===


def get_discord_service_api_key(db_session: Session) -> ApiKey | None:
    """Get the Discord service API key if it exists."""
    return db_session.scalar(
        select(ApiKey).where(ApiKey.name == DISCORD_SERVICE_API_KEY_NAME)
    )


def get_or_create_discord_service_api_key(
    db_session: Session,
    tenant_id: str,
) -> str:
    """Get existing Discord service API key or create one.

    The API key is used by the Discord bot to authenticate with the
    Onyx API pods when sending chat requests.

    Args:
        db_session: Database session for the tenant.
        tenant_id: The tenant ID (used for logging/context).

    Returns:
        The raw API key string (not hashed).

    Raises:
        RuntimeError: If API key creation fails.
    """
    # Check for existing key
    existing = get_discord_service_api_key(db_session)
    if existing:
        # Database only stores the hash, so we must regenerate to get the raw key.
        # This is safe since the Discord bot is the only consumer of this key.
        logger.debug(
            f"Found existing Discord service API key for tenant {tenant_id} that isn't in cache, "
            "regenerating to update cache"
        )
        new_api_key = generate_api_key(tenant_id)
        existing.hashed_api_key = hash_api_key(new_api_key)
        existing.api_key_display = build_displayable_api_key(new_api_key)
        db_session.flush()
        return new_api_key

    # Create new API key
    logger.info(f"Creating Discord service API key for tenant {tenant_id}")
    api_key_args = APIKeyArgs(
        name=DISCORD_SERVICE_API_KEY_NAME,
        role=UserRole.LIMITED,  # Limited role is sufficient for chat requests
    )
    api_key_descriptor = insert_api_key(
        db_session=db_session,
        api_key_args=api_key_args,
        user_id=None,  # Service account, no owner
    )

    if not api_key_descriptor.api_key:
        raise RuntimeError(
            f"Failed to create Discord service API key for tenant {tenant_id}"
        )

    return api_key_descriptor.api_key


def delete_discord_service_api_key(db_session: Session) -> bool:
    """Delete the Discord service API key for a tenant.

    Called when:
    - Bot config is deleted (self-hosted)
    - All guild configs are deleted (Cloud)

    Args:
        db_session: Database session for the tenant.

    Returns:
        True if the key was deleted, False if it didn't exist.
    """
    existing_key = get_discord_service_api_key(db_session)
    if not existing_key:
        return False

    # Also delete the associated user
    api_key_user = db_session.scalar(
        select(User).where(User.id == existing_key.user_id)  # type: ignore[arg-type]
    )

    db_session.delete(existing_key)
    if api_key_user:
        db_session.delete(api_key_user)

    db_session.flush()
    logger.info("Deleted Discord service API key")
    return True


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
    default_persona_id: int | None = None,
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
    return result.rowcount > 0  # type: ignore[attr-defined]


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
    enabled: bool,
    persona_override_id: int | None = None,
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
    return result.rowcount > 0  # type: ignore[attr-defined]


def create_channel_config(
    db_session: Session,
    guild_config_id: int,
    channel_view: DiscordChannelView,
) -> DiscordChannelConfig:
    """Create a new channel config with default settings (disabled by default, admin enables via UI)."""
    config = DiscordChannelConfig(
        guild_config_id=guild_config_id,
        channel_id=channel_view.channel_id,
        channel_name=channel_view.channel_name,
        channel_type=channel_view.channel_type,
        is_private=channel_view.is_private,
    )
    db_session.add(config)
    db_session.flush()
    return config


def bulk_create_channel_configs(
    db_session: Session,
    guild_config_id: int,
    channels: list[DiscordChannelView],
) -> list[DiscordChannelConfig]:
    """Create multiple channel configs at once. Skips existing channels."""
    # Get existing channel IDs for this guild
    existing_channel_ids = set(
        db_session.scalars(
            select(DiscordChannelConfig.channel_id).where(
                DiscordChannelConfig.guild_config_id == guild_config_id
            )
        ).all()
    )

    # Create configs for new channels only
    new_configs = []
    for channel_view in channels:
        if channel_view.channel_id not in existing_channel_ids:
            config = DiscordChannelConfig(
                guild_config_id=guild_config_id,
                channel_id=channel_view.channel_id,
                channel_name=channel_view.channel_name,
                channel_type=channel_view.channel_type,
                is_private=channel_view.is_private,
            )
            db_session.add(config)
            new_configs.append(config)

    db_session.flush()
    return new_configs


def sync_channel_configs(
    db_session: Session,
    guild_config_id: int,
    current_channels: list[DiscordChannelView],
) -> tuple[int, int, int]:
    """Sync channel configs with current Discord channels.

    - Creates configs for new channels (disabled by default)
    - Removes configs for deleted channels
    - Updates names and types for existing channels if changed

    Returns: (added_count, removed_count, updated_count)
    """
    current_channel_map = {
        channel_view.channel_id: channel_view for channel_view in current_channels
    }
    current_channel_ids = set(current_channel_map.keys())

    # Get existing configs
    existing_configs = get_channel_configs(db_session, guild_config_id)
    existing_channel_ids = {c.channel_id for c in existing_configs}

    # Find channels to add, remove, and potentially update
    to_add = current_channel_ids - existing_channel_ids
    to_remove = existing_channel_ids - current_channel_ids

    # Add new channels
    added_count = 0
    for channel_id in to_add:
        channel_view = current_channel_map[channel_id]
        create_channel_config(db_session, guild_config_id, channel_view)
        added_count += 1

    # Remove deleted channels
    removed_count = 0
    for config in existing_configs:
        if config.channel_id in to_remove:
            db_session.delete(config)
            removed_count += 1

    # Update names, types, and privacy for existing channels if changed
    updated_count = 0
    for config in existing_configs:
        if config.channel_id in current_channel_ids:
            channel_view = current_channel_map[config.channel_id]
            changed = False
            if config.channel_name != channel_view.channel_name:
                config.channel_name = channel_view.channel_name
                changed = True
            if config.channel_type != channel_view.channel_type:
                config.channel_type = channel_view.channel_type
                changed = True
            if config.is_private != channel_view.is_private:
                config.is_private = channel_view.is_private
                changed = True
            if changed:
                updated_count += 1

    db_session.flush()
    return added_count, removed_count, updated_count
