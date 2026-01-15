"""Discord bot admin API endpoints."""

from uuid import UUID

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import status
from sqlalchemy.orm import Session

from onyx.auth.users import current_admin_user
from onyx.configs.app_configs import AUTH_TYPE
from onyx.configs.app_configs import DISCORD_BOT_TOKEN
from onyx.configs.constants import AuthType
from onyx.db.discord_bot import create_discord_bot_config
from onyx.db.discord_bot import create_discord_channel_config
from onyx.db.discord_bot import create_discord_guild_config
from onyx.db.discord_bot import delete_discord_bot_config
from onyx.db.discord_bot import delete_discord_channel_config
from onyx.db.discord_bot import delete_discord_guild_config
from onyx.db.discord_bot import get_discord_bot_config
from onyx.db.discord_bot import get_discord_channel_config
from onyx.db.discord_bot import get_discord_channel_configs
from onyx.db.discord_bot import get_discord_guild_config_by_id
from onyx.db.discord_bot import get_discord_guild_configs
from onyx.db.discord_bot import update_discord_channel_config
from onyx.db.discord_bot import update_discord_guild_config
from onyx.db.engine import get_session
from onyx.db.models import User
from onyx.server.manage.discord_bot.models import DiscordBotConfigCreateRequest
from onyx.server.manage.discord_bot.models import DiscordBotConfigResponse
from onyx.server.manage.discord_bot.models import DiscordChannelConfigCreateRequest
from onyx.server.manage.discord_bot.models import DiscordChannelConfigResponse
from onyx.server.manage.discord_bot.models import DiscordChannelConfigUpdateRequest
from onyx.server.manage.discord_bot.models import DiscordGuildConfigCreateResponse
from onyx.server.manage.discord_bot.models import DiscordGuildConfigResponse
from onyx.server.manage.discord_bot.models import DiscordGuildConfigUpdateRequest
from onyx.server.manage.discord_bot.registration_key import (
    generate_discord_registration_key,
)
from shared_configs.contextvars import get_current_tenant_id

router = APIRouter(prefix="/manage/admin/discord-bot")


def _check_bot_config_api_access() -> None:
    """Raise 403 if bot config cannot be managed via API.

    Bot config endpoints are disabled:
    - On Cloud (managed by Onyx)
    - When DISCORD_BOT_TOKEN env var is set (managed via env)
    """
    if AUTH_TYPE == AuthType.CLOUD:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Discord bot configuration is managed by Onyx on Cloud.",
        )
    if DISCORD_BOT_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Discord bot is configured via environment variables. API access disabled.",
        )


# === Bot Config ===


@router.get("/config", response_model=DiscordBotConfigResponse)
def get_bot_config(
    _: None = Depends(_check_bot_config_api_access),
    __: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> DiscordBotConfigResponse:
    """Get Discord bot config. Returns 403 on Cloud or if env vars set."""
    config = get_discord_bot_config(db_session)
    if not config:
        return DiscordBotConfigResponse(configured=False)

    return DiscordBotConfigResponse(
        configured=True,
        created_at=config.created_at,
    )


@router.post("/config", response_model=DiscordBotConfigResponse)
def create_bot_config(
    request: DiscordBotConfigCreateRequest,
    _: None = Depends(_check_bot_config_api_access),
    __: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> DiscordBotConfigResponse:
    """Create Discord bot config. Returns 403 on Cloud or if env vars set."""
    try:
        config = create_discord_bot_config(
            db_session,
            bot_token=request.bot_token,
        )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Discord bot config already exists. Delete it first to create a new one.",
        )

    db_session.commit()

    return DiscordBotConfigResponse(
        configured=True,
        created_at=config.created_at,
    )


@router.delete("/config")
def delete_bot_config_endpoint(
    _: None = Depends(_check_bot_config_api_access),
    __: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> dict:
    """Delete Discord bot config."""
    deleted = delete_discord_bot_config(db_session)
    db_session.commit()

    return {"deleted": deleted}


# === Guild Config ===


@router.get("/guilds", response_model=list[DiscordGuildConfigResponse])
def list_guild_configs(
    _: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> list[DiscordGuildConfigResponse]:
    """List all guild configs (pending and registered)."""
    configs = get_discord_guild_configs(db_session)
    return [DiscordGuildConfigResponse.model_validate(c) for c in configs]


@router.post("/guilds", response_model=DiscordGuildConfigCreateResponse)
def create_guild_config(
    _: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> DiscordGuildConfigCreateResponse:
    """Create new guild config with registration key. Key shown once."""
    tenant_id = get_current_tenant_id()
    registration_key = generate_discord_registration_key(tenant_id)

    config = create_discord_guild_config(db_session, registration_key)
    db_session.commit()

    return DiscordGuildConfigCreateResponse(
        id=config.id,
        registration_key=registration_key,  # Shown once!
    )


@router.get("/guilds/{config_id}", response_model=DiscordGuildConfigResponse)
def get_guild_config(
    config_id: UUID,
    _: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> DiscordGuildConfigResponse:
    """Get specific guild config."""
    config = get_discord_guild_config_by_id(db_session, config_id)
    if not config:
        raise HTTPException(status_code=404, detail="Guild config not found")
    return DiscordGuildConfigResponse.model_validate(config)


@router.patch("/guilds/{config_id}", response_model=DiscordGuildConfigResponse)
def update_guild_config_endpoint(
    config_id: UUID,
    request: DiscordGuildConfigUpdateRequest,
    _: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> DiscordGuildConfigResponse:
    """Update guild config."""
    config = get_discord_guild_config_by_id(db_session, config_id)
    if not config:
        raise HTTPException(status_code=404, detail="Guild config not found")

    config = update_discord_guild_config(
        db_session,
        config,
        enabled=request.enabled,
        respond_in_all_public_channels=request.respond_in_all_public_channels,
        default_persona_id=request.default_persona_id,
    )
    db_session.commit()

    return DiscordGuildConfigResponse.model_validate(config)


@router.delete("/guilds/{config_id}")
def delete_guild_config_endpoint(
    config_id: UUID,
    _: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> dict:
    """Delete guild config (invalidates registration key)."""
    deleted = delete_discord_guild_config(db_session, config_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Guild config not found")
    db_session.commit()
    return {"deleted": True}


# === Channel Config ===


@router.get(
    "/guilds/{config_id}/channels", response_model=list[DiscordChannelConfigResponse]
)
def list_channel_configs(
    config_id: UUID,
    _: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> list[DiscordChannelConfigResponse]:
    """List whitelisted channels for a guild."""
    guild_config = get_discord_guild_config_by_id(db_session, config_id)
    if not guild_config:
        raise HTTPException(status_code=404, detail="Guild config not found")
    if not guild_config.guild_id:
        raise HTTPException(status_code=400, detail="Guild not yet registered")

    configs = get_discord_channel_configs(db_session, config_id)
    return [DiscordChannelConfigResponse.model_validate(c) for c in configs]


@router.post(
    "/guilds/{config_id}/channels", response_model=DiscordChannelConfigResponse
)
def create_channel_config(
    config_id: UUID,
    request: DiscordChannelConfigCreateRequest,
    _: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> DiscordChannelConfigResponse:
    """Add channel to whitelist."""
    guild_config = get_discord_guild_config_by_id(db_session, config_id)
    if not guild_config:
        raise HTTPException(status_code=404, detail="Guild config not found")
    if not guild_config.guild_id:
        raise HTTPException(status_code=400, detail="Guild not yet registered")

    # Check if channel already exists
    existing = get_discord_channel_config(db_session, config_id, request.channel_id)
    if existing:
        raise HTTPException(status_code=409, detail="Channel already configured")

    config = create_discord_channel_config(
        db_session,
        guild_config_id=config_id,
        channel_id=request.channel_id,
        channel_name=request.channel_name,
        require_bot_invocation=request.require_bot_invocation,
        persona_override_id=request.persona_override_id,
    )
    db_session.commit()

    return DiscordChannelConfigResponse.model_validate(config)


@router.patch(
    "/guilds/{config_id}/channels/{channel_id}",
    response_model=DiscordChannelConfigResponse,
)
def update_channel_config_endpoint(
    config_id: UUID,
    channel_id: int,
    request: DiscordChannelConfigUpdateRequest,
    _: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> DiscordChannelConfigResponse:
    """Update channel config."""
    config = get_discord_channel_config(db_session, config_id, channel_id)
    if not config:
        raise HTTPException(status_code=404, detail="Channel config not found")

    config = update_discord_channel_config(
        db_session,
        config,
        channel_name=request.channel_name,
        require_bot_invocation=request.require_bot_invocation,
        persona_override_id=request.persona_override_id,
        enabled=request.enabled,
    )
    db_session.commit()

    return DiscordChannelConfigResponse.model_validate(config)


@router.delete("/guilds/{config_id}/channels/{channel_id}")
def delete_channel_config_endpoint(
    config_id: UUID,
    channel_id: int,
    _: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> dict:
    """Remove channel from whitelist."""
    deleted = delete_discord_channel_config(db_session, config_id, channel_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Channel config not found")
    db_session.commit()
    return {"deleted": True}
