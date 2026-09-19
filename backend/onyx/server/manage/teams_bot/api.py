from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.configs.onyxbot_configs import ENABLE_TEAMS_BOT
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.db.persona import get_persona_by_id
from onyx.db.teams_bot import (
    create_teams_bot_config,
    delete_teams_bot_config,
    get_teams_bot_config,
    update_teams_bot_config,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.manage.teams_bot.models import (
    TeamsBotConfigCreate,
    TeamsBotConfigResponse,
    TeamsBotConfigUpdate,
)
from shared_configs.configs import MULTI_TENANT


def check_teams_bot_available() -> None:
    if not ENABLE_TEAMS_BOT:
        raise OnyxError(OnyxErrorCode.NOT_FOUND)
    if MULTI_TENANT:
        raise OnyxError(OnyxErrorCode.SINGLE_TENANT_ONLY)


router = APIRouter(
    prefix="/manage/admin/teams-bot",
    dependencies=[Depends(check_teams_bot_available)],
)


def validate_persona(persona_id: int | None, user: User, db_session: Session) -> None:
    if persona_id is None:
        return
    try:
        get_persona_by_id(persona_id, user, db_session, is_for_edit=False)
    except ValueError as exc:
        raise OnyxError(OnyxErrorCode.PERSONA_NOT_FOUND) from exc


@router.get("/config")
def read_teams_bot_config(
    _: User = Depends(require_permission(Permission.MANAGE_BOTS)),
    db_session: Session = Depends(get_session),
) -> TeamsBotConfigResponse | None:
    config = get_teams_bot_config(db_session)
    return TeamsBotConfigResponse.model_validate(config) if config else None


@router.post("/config")
def create_teams_bot_config_endpoint(
    request: TeamsBotConfigCreate,
    user: User = Depends(require_permission(Permission.MANAGE_BOTS)),
    db_session: Session = Depends(get_session),
) -> TeamsBotConfigResponse:
    validate_persona(request.persona_id, user, db_session)
    config = create_teams_bot_config(db_session, request)
    db_session.commit()
    return TeamsBotConfigResponse.model_validate(config)


@router.put("/config")
def update_teams_bot_config_endpoint(
    request: TeamsBotConfigUpdate,
    user: User = Depends(require_permission(Permission.MANAGE_BOTS)),
    db_session: Session = Depends(get_session),
) -> TeamsBotConfigResponse:
    validate_persona(request.persona_id, user, db_session)
    config = update_teams_bot_config(db_session, request)
    db_session.commit()
    return TeamsBotConfigResponse.model_validate(config)


@router.delete("/config")
def delete_teams_bot_config_endpoint(
    _: User = Depends(require_permission(Permission.MANAGE_BOTS)),
    db_session: Session = Depends(get_session),
) -> None:
    delete_teams_bot_config(db_session)
    db_session.commit()
