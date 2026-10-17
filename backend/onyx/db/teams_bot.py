from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from onyx.db.models import EncryptedString, TeamsBotConfig
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.manage.teams_bot.models import (
    TeamsBotConfigCreate,
    TeamsBotConfigUpdate,
)


def get_teams_bot_config(db_session: Session) -> TeamsBotConfig | None:
    return db_session.get(TeamsBotConfig, 1)


def create_teams_bot_config(
    db_session: Session, request: TeamsBotConfigCreate
) -> TeamsBotConfig:
    config = TeamsBotConfig(
        id=1,
        app_id=request.app_id,
        directory_id=request.directory_id,
        client_secret=request.client_secret.get_secret_value(),
        enabled=request.enabled,
        persona_id=request.persona_id,
    )
    try:
        with db_session.begin_nested():
            db_session.add(config)
            db_session.flush()
    except IntegrityError as exc:
        if get_teams_bot_config(db_session) is not None:
            raise OnyxError(
                OnyxErrorCode.CONFLICT, "Teams bot configuration already exists."
            ) from exc
        raise
    return config


def update_teams_bot_config(
    db_session: Session, request: TeamsBotConfigUpdate
) -> TeamsBotConfig:
    config = get_teams_bot_config(db_session)
    if config is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND)
    config.enabled = request.enabled
    config.persona_id = request.persona_id
    if request.client_secret is not None:
        config.client_secret = EncryptedString().wrap_raw(
            request.client_secret.get_secret_value()
        )
    db_session.flush()
    return config


def delete_teams_bot_config(db_session: Session) -> None:
    config = get_teams_bot_config(db_session)
    if config is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND)
    db_session.delete(config)
    db_session.flush()
