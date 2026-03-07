"""Teams bot admin API endpoints."""

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import status
from sqlalchemy.orm import Session

from onyx.auth.users import current_admin_user
from onyx.configs.app_configs import AUTH_TYPE
from onyx.configs.app_configs import TEAMS_BOT_APP_ID
from onyx.configs.constants import AuthType
from onyx.db.engine.sql_engine import get_session
from onyx.db.models import User
from onyx.db.teams_bot import create_team_config
from onyx.db.teams_bot import create_teams_bot_config
from onyx.db.teams_bot import delete_team_config
from onyx.db.teams_bot import delete_teams_bot_config
from onyx.db.teams_bot import delete_teams_service_api_key
from onyx.db.teams_bot import get_channel_config_by_internal_ids
from onyx.db.teams_bot import get_channel_configs
from onyx.db.teams_bot import get_team_config_by_internal_id
from onyx.db.teams_bot import get_team_configs
from onyx.db.teams_bot import get_teams_bot_config
from onyx.db.teams_bot import update_team_config
from onyx.db.teams_bot import update_teams_channel_config
from onyx.server.manage.teams_bot.models import TeamsBotConfigCreateRequest
from onyx.server.manage.teams_bot.models import TeamsBotConfigResponse
from onyx.server.manage.teams_bot.models import TeamsChannelConfigResponse
from onyx.server.manage.teams_bot.models import TeamsChannelConfigUpdateRequest
from onyx.server.manage.teams_bot.models import TeamsTeamConfigCreateResponse
from onyx.server.manage.teams_bot.models import TeamsTeamConfigResponse
from onyx.server.manage.teams_bot.models import TeamsTeamConfigUpdateRequest
from onyx.server.manage.teams_bot.utils import generate_teams_registration_key
from shared_configs.contextvars import get_current_tenant_id

router = APIRouter(prefix="/manage/admin/teams-bot")


def _check_bot_config_api_access() -> None:
    """Raise 403 if bot config cannot be managed via API.

    Bot config endpoints are disabled:
    - On Cloud (managed by Onyx)
    - When TEAMS_BOT_APP_ID env var is set (managed via env)
    """
    if AUTH_TYPE == AuthType.CLOUD:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Teams bot configuration is managed by Onyx on Cloud.",
        )
    if TEAMS_BOT_APP_ID:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Teams bot is configured via environment variables. API access disabled.",
        )


# === Bot Config ===


@router.get("/config")
def get_bot_config(
    _: None = Depends(_check_bot_config_api_access),
    __: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> TeamsBotConfigResponse:
    """Get Teams bot config. Returns 403 on Cloud or if env vars set."""
    config = get_teams_bot_config(db_session)
    if not config:
        return TeamsBotConfigResponse(configured=False)

    return TeamsBotConfigResponse(
        configured=True,
        created_at=config.created_at,
    )


@router.post("/config")
def create_bot_request(
    request: TeamsBotConfigCreateRequest,
    _: None = Depends(_check_bot_config_api_access),
    __: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> TeamsBotConfigResponse:
    """Create Teams bot config. Returns 403 on Cloud or if env vars set."""
    try:
        config = create_teams_bot_config(
            db_session,
            app_id=request.app_id,
            app_secret=request.app_secret,
            azure_tenant_id=request.azure_tenant_id,
        )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Teams bot config already exists. Delete it first to create a new one.",
        )

    db_session.commit()

    return TeamsBotConfigResponse(
        configured=True,
        created_at=config.created_at,
    )


@router.delete("/config")
def delete_bot_config_endpoint(
    _: None = Depends(_check_bot_config_api_access),
    __: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> dict:
    """Delete Teams bot config.

    Also deletes the Teams service API key since the bot is being removed.
    """
    deleted = delete_teams_bot_config(db_session)
    if not deleted:
        raise HTTPException(status_code=404, detail="Bot config not found")

    delete_teams_service_api_key(db_session)

    db_session.commit()
    return {"deleted": True}


# === Service API Key ===


@router.delete("/service-api-key")
def delete_service_api_key_endpoint(
    _: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> dict:
    """Delete the Teams service API key."""
    deleted = delete_teams_service_api_key(db_session)
    if not deleted:
        raise HTTPException(status_code=404, detail="Service API key not found")
    db_session.commit()
    return {"deleted": True}


# === Team Config ===


@router.get("/teams")
def list_team_configs(
    _: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> list[TeamsTeamConfigResponse]:
    """List all team configs (pending and registered)."""
    configs = get_team_configs(db_session)
    return [TeamsTeamConfigResponse.model_validate(c) for c in configs]


@router.post("/teams")
def create_team_request(
    _: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> TeamsTeamConfigCreateResponse:
    """Create new team config with registration key. Key shown once."""
    tenant_id = get_current_tenant_id()
    registration_key = generate_teams_registration_key(tenant_id)

    config = create_team_config(db_session, registration_key)
    db_session.commit()

    return TeamsTeamConfigCreateResponse(
        id=config.id,
        registration_key=registration_key,
    )


@router.get("/teams/{config_id}")
def get_team_config(
    config_id: int,
    _: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> TeamsTeamConfigResponse:
    """Get specific team config."""
    config = get_team_config_by_internal_id(db_session, internal_id=config_id)
    if not config:
        raise HTTPException(status_code=404, detail="Team config not found")
    return TeamsTeamConfigResponse.model_validate(config)


@router.patch("/teams/{config_id}")
def update_team_request(
    config_id: int,
    request: TeamsTeamConfigUpdateRequest,
    _: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> TeamsTeamConfigResponse:
    """Update team config."""
    config = get_team_config_by_internal_id(db_session, internal_id=config_id)
    if not config:
        raise HTTPException(status_code=404, detail="Team config not found")

    config = update_team_config(
        db_session,
        config,
        enabled=request.enabled,
        default_persona_id=request.default_persona_id,
    )
    db_session.commit()

    return TeamsTeamConfigResponse.model_validate(config)


@router.delete("/teams/{config_id}")
def delete_team_request(
    config_id: int,
    _: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> dict:
    """Delete team config (invalidates registration key).

    On Cloud, if this was the last team config, also deletes the service API key.
    """
    deleted = delete_team_config(db_session, config_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Team config not found")

    if AUTH_TYPE == AuthType.CLOUD:
        remaining_teams = get_team_configs(db_session)
        if not remaining_teams:
            delete_teams_service_api_key(db_session)

    db_session.commit()
    return {"deleted": True}


# === Channel Config ===


@router.get("/teams/{config_id}/channels")
def list_channel_configs(
    config_id: int,
    _: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> list[TeamsChannelConfigResponse]:
    """List whitelisted channels for a team."""
    team_config = get_team_config_by_internal_id(db_session, internal_id=config_id)
    if not team_config:
        raise HTTPException(status_code=404, detail="Team config not found")
    if not team_config.team_id:
        raise HTTPException(status_code=400, detail="Team not yet registered")

    configs = get_channel_configs(db_session, config_id)
    return [TeamsChannelConfigResponse.model_validate(c) for c in configs]


@router.patch("/teams/{team_config_id}/channels/{channel_config_id}")
def update_channel_request(
    team_config_id: int,
    channel_config_id: int,
    request: TeamsChannelConfigUpdateRequest,
    _: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> TeamsChannelConfigResponse:
    """Update channel config."""
    config = get_channel_config_by_internal_ids(
        db_session, team_config_id, channel_config_id
    )
    if not config:
        raise HTTPException(status_code=404, detail="Channel config not found")

    config = update_teams_channel_config(
        db_session,
        config,
        channel_name=config.channel_name,  # Keep existing name
        require_bot_mention=request.require_bot_mention,
        persona_override_id=request.persona_override_id,
        enabled=request.enabled,
    )
    db_session.commit()

    return TeamsChannelConfigResponse.model_validate(config)
