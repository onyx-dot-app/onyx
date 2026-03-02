"""CRUD operations for Teams bot models."""

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
from onyx.configs.constants import TEAMS_SERVICE_API_KEY_NAME
from onyx.db.api_key import insert_api_key
from onyx.db.models import ApiKey
from onyx.db.models import TeamsBotConfig
from onyx.db.models import TeamsChannelConfig
from onyx.db.models import TeamsTeamConfig
from onyx.db.models import User
from onyx.server.api_key.models import APIKeyArgs
from onyx.utils.logger import setup_logger

logger = setup_logger()


# === TeamsBotConfig ===


def get_teams_bot_config(db_session: Session) -> TeamsBotConfig | None:
    """Get the Teams bot config for this tenant (at most one)."""
    return db_session.scalar(select(TeamsBotConfig).limit(1))


def create_teams_bot_config(
    db_session: Session,
    app_id: str,
    app_secret: str,
    azure_tenant_id: str | None = None,
) -> TeamsBotConfig:
    """Create the Teams bot config. Raises ValueError if already exists.

    The check constraint on id='SINGLETON' ensures only one config per tenant.
    """
    existing = get_teams_bot_config(db_session)
    if existing:
        raise ValueError("Teams bot config already exists")

    config = TeamsBotConfig(
        app_id=app_id,
        app_secret=app_secret,
        azure_tenant_id=azure_tenant_id,
    )
    db_session.add(config)
    try:
        db_session.flush()
    except IntegrityError:
        db_session.rollback()
        raise ValueError("Teams bot config already exists")
    return config


def delete_teams_bot_config(db_session: Session) -> bool:
    """Delete the Teams bot config. Returns True if deleted."""
    result = db_session.execute(delete(TeamsBotConfig))
    db_session.flush()
    return result.rowcount > 0  # type: ignore[attr-defined]


# === Teams Service API Key ===


def get_teams_service_api_key(db_session: Session) -> ApiKey | None:
    """Get the Teams service API key if it exists."""
    return db_session.scalar(
        select(ApiKey).where(ApiKey.name == TEAMS_SERVICE_API_KEY_NAME)
    )


def get_or_create_teams_service_api_key(
    db_session: Session,
    tenant_id: str,
) -> str:
    """Get existing Teams service API key or create one.

    The API key is used by the Teams bot to authenticate with the
    Onyx API pods when sending chat requests.

    Returns:
        The raw API key string (not hashed).
    """
    existing = get_teams_service_api_key(db_session)
    if existing:
        # Database only stores the hash, so we must regenerate to get the raw key.
        logger.debug(
            f"Found existing Teams service API key for tenant {tenant_id} that isn't in cache, "
            "regenerating to update cache"
        )
        new_api_key = generate_api_key(tenant_id)
        existing.hashed_api_key = hash_api_key(new_api_key)
        existing.api_key_display = build_displayable_api_key(new_api_key)
        db_session.flush()
        return new_api_key

    logger.info(f"Creating Teams service API key for tenant {tenant_id}")
    api_key_args = APIKeyArgs(
        name=TEAMS_SERVICE_API_KEY_NAME,
        role=UserRole.LIMITED,
    )
    api_key_descriptor = insert_api_key(
        db_session=db_session,
        api_key_args=api_key_args,
        user_id=None,
    )

    if not api_key_descriptor.api_key:
        raise RuntimeError(
            f"Failed to create Teams service API key for tenant {tenant_id}"
        )

    return api_key_descriptor.api_key


def delete_teams_service_api_key(db_session: Session) -> bool:
    """Delete the Teams service API key for a tenant.

    Called when:
    - Bot config is deleted (self-hosted)
    - All team configs are deleted (Cloud)
    """
    existing_key = get_teams_service_api_key(db_session)
    if not existing_key:
        return False

    api_key_user = db_session.scalar(
        select(User).where(User.id == existing_key.user_id)  # type: ignore[arg-type]
    )

    db_session.delete(existing_key)
    if api_key_user:
        db_session.delete(api_key_user)

    db_session.flush()
    logger.info("Deleted Teams service API key")
    return True


# === TeamsTeamConfig ===


def get_team_configs(
    db_session: Session,
    include_channels: bool = False,
) -> list[TeamsTeamConfig]:
    """Get all team configs for this tenant."""
    stmt = select(TeamsTeamConfig)
    if include_channels:
        stmt = stmt.options(joinedload(TeamsTeamConfig.channels))
    return list(db_session.scalars(stmt).unique().all())


def get_team_config_by_internal_id(
    db_session: Session,
    internal_id: int,
) -> TeamsTeamConfig | None:
    """Get a specific team config by its ID."""
    return db_session.scalar(
        select(TeamsTeamConfig).where(TeamsTeamConfig.id == internal_id)
    )


def get_team_config_by_teams_id(
    db_session: Session,
    team_id: str,
) -> TeamsTeamConfig | None:
    """Get a team config by Teams team ID."""
    return db_session.scalar(
        select(TeamsTeamConfig).where(TeamsTeamConfig.team_id == team_id)
    )


def get_team_config_by_registration_key(
    db_session: Session,
    registration_key: str,
) -> TeamsTeamConfig | None:
    """Get a team config by its registration key."""
    return db_session.scalar(
        select(TeamsTeamConfig).where(
            TeamsTeamConfig.registration_key == registration_key
        )
    )


def create_team_config(
    db_session: Session,
    registration_key: str,
) -> TeamsTeamConfig:
    """Create a new team config with a registration key (team_id=NULL)."""
    config = TeamsTeamConfig(registration_key=registration_key)
    db_session.add(config)
    db_session.flush()
    return config


def register_team(
    db_session: Session,
    config: TeamsTeamConfig,
    team_id: str,
    team_name: str,
) -> TeamsTeamConfig:
    """Complete registration by setting team_id and team_name."""
    config.team_id = team_id
    config.team_name = team_name
    config.registered_at = datetime.now(timezone.utc)
    db_session.flush()
    return config


def update_team_config(
    db_session: Session,
    config: TeamsTeamConfig,
    enabled: bool,
    default_persona_id: int | None = None,
) -> TeamsTeamConfig:
    """Update team config fields."""
    config.enabled = enabled
    config.default_persona_id = default_persona_id
    db_session.flush()
    return config


def delete_team_config(
    db_session: Session,
    internal_id: int,
) -> bool:
    """Delete team config (cascades to channel configs). Returns True if deleted."""
    result = db_session.execute(
        delete(TeamsTeamConfig).where(TeamsTeamConfig.id == internal_id)
    )
    db_session.flush()
    return result.rowcount > 0  # type: ignore[attr-defined]


# === TeamsChannelConfig ===


def get_channel_configs(
    db_session: Session,
    team_config_id: int,
) -> list[TeamsChannelConfig]:
    """Get all channel configs for a team."""
    return list(
        db_session.scalars(
            select(TeamsChannelConfig).where(
                TeamsChannelConfig.team_config_id == team_config_id
            )
        ).all()
    )


def get_channel_config_by_teams_ids(
    db_session: Session,
    team_id: str,
    channel_id: str,
) -> TeamsChannelConfig | None:
    """Get a specific channel config by team_id and channel_id."""
    return db_session.scalar(
        select(TeamsChannelConfig)
        .join(TeamsTeamConfig)
        .where(
            TeamsTeamConfig.team_id == team_id,
            TeamsChannelConfig.channel_id == channel_id,
        )
    )


def get_channel_config_by_internal_ids(
    db_session: Session,
    team_config_id: int,
    channel_config_id: int,
) -> TeamsChannelConfig | None:
    """Get a specific channel config by team_config_id and channel_config_id."""
    return db_session.scalar(
        select(TeamsChannelConfig).where(
            TeamsChannelConfig.team_config_id == team_config_id,
            TeamsChannelConfig.id == channel_config_id,
        )
    )


def update_teams_channel_config(
    db_session: Session,
    config: TeamsChannelConfig,
    channel_name: str,
    require_bot_mention: bool,
    enabled: bool,
    persona_override_id: int | None = None,
) -> TeamsChannelConfig:
    """Update channel config fields."""
    config.channel_name = channel_name
    config.require_bot_mention = require_bot_mention
    config.persona_override_id = persona_override_id
    config.enabled = enabled
    db_session.flush()
    return config


def create_channel_config(
    db_session: Session,
    team_config_id: int,
    channel_id: str,
    channel_name: str,
) -> TeamsChannelConfig:
    """Create a new channel config with default settings (disabled by default)."""
    config = TeamsChannelConfig(
        team_config_id=team_config_id,
        channel_id=channel_id,
        channel_name=channel_name,
    )
    db_session.add(config)
    db_session.flush()
    return config
