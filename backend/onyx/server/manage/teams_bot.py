from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from sqlalchemy.orm import Session

from onyx.auth.users import current_admin_user
from onyx.configs.constants import MilestoneRecordType
from onyx.db.engine import get_session
from onyx.db.models import ChannelConfig
from onyx.db.models import User
from onyx.db.persona import get_persona_by_id
from onyx.db.teams_bot import fetch_teams_bot
from onyx.db.teams_bot import fetch_teams_bot_tokens
from onyx.db.teams_bot import fetch_teams_bots
from onyx.db.teams_bot import insert_teams_bot
from onyx.db.teams_bot import remove_teams_bot
from onyx.db.teams_bot import update_teams_bot
from onyx.db.teams_channel_config import create_teams_channel_persona
from onyx.db.teams_channel_config import fetch_teams_channel_config
from onyx.db.teams_channel_config import fetch_teams_channel_configs
from onyx.db.teams_channel_config import insert_teams_channel_config
from onyx.db.teams_channel_config import remove_teams_channel_config
from onyx.db.teams_channel_config import update_teams_channel_config
from onyx.onyxbot.teams.config import validate_channel_name
from onyx.server.manage.models import TeamsBot
from onyx.server.manage.models import TeamsBotCreationRequest
from onyx.server.manage.models import TeamsChannelConfig
from onyx.server.manage.models import TeamsChannelConfigCreationRequest
from onyx.utils.logger import setup_logger
from onyx.utils.telemetry import create_milestone_and_report
from shared_configs.contextvars import get_current_tenant_id


logger = setup_logger()


router = APIRouter(prefix="/manage")


def _form_channel_config(
    db_session: Session,
    teams_channel_config_creation_request: TeamsChannelConfigCreationRequest,
    current_teams_channel_config_id: int | None,
) -> ChannelConfig:
    channel_config = ChannelConfig(
        channel_name=teams_channel_config_creation_request.channel_name,
        respond_tag_only=teams_channel_config_creation_request.respond_tag_only,
    )

    if current_teams_channel_config_id is not None:
        current_teams_channel_config = fetch_teams_channel_config(
            db_session=db_session,
            teams_channel_config_id=current_teams_channel_config_id,
        )
        if current_teams_channel_config:
            channel_config = current_teams_channel_config.channel_config

    return channel_config


@router.post("/admin/teams-app/channel")
def create_teams_channel_config(
    teams_channel_config_creation_request: TeamsChannelConfigCreationRequest,
    db_session: Session = Depends(get_session),
    _: User | None = Depends(current_admin_user),
) -> TeamsChannelConfig:
    channel_config = _form_channel_config(
        db_session=db_session,
        teams_channel_config_creation_request=teams_channel_config_creation_request,
        current_teams_channel_config_id=None,
    )

    if channel_config["channel_name"] is None:
        raise HTTPException(
            status_code=400,
            detail="Channel name is required",
        )

    persona_id = None
    if teams_channel_config_creation_request.persona_id is not None:
        persona_id = teams_channel_config_creation_request.persona_id
    elif teams_channel_config_creation_request.document_sets:
        persona_id = create_teams_channel_persona(
            db_session=db_session,
            channel_name=channel_config["channel_name"],
            document_set_ids=teams_channel_config_creation_request.document_sets,
            existing_persona_id=None,
        ).id

    teams_channel_config_model = insert_teams_channel_config(
        db_session=db_session,
        teams_bot_id=teams_channel_config_creation_request.teams_bot_id,
        persona_id=persona_id,
        channel_config=channel_config,
        standard_answer_category_ids=teams_channel_config_creation_request.standard_answer_categories,
        enable_auto_filters=teams_channel_config_creation_request.enable_auto_filters,
    )
    return TeamsChannelConfig.from_model(teams_channel_config_model)


@router.patch("/admin/teams-app/channel/{teams_channel_config_id}")
def patch_teams_channel_config(
    teams_channel_config_id: int,
    teams_channel_config_creation_request: TeamsChannelConfigCreationRequest,
    db_session: Session = Depends(get_session),
    _: User | None = Depends(current_admin_user),
) -> TeamsChannelConfig:
    channel_config = _form_channel_config(
        db_session=db_session,
        teams_channel_config_creation_request=teams_channel_config_creation_request,
        current_teams_channel_config_id=teams_channel_config_id,
    )

    persona_id = None
    if teams_channel_config_creation_request.persona_id is not None:
        persona_id = teams_channel_config_creation_request.persona_id
    elif teams_channel_config_creation_request.document_sets:
        persona_id = create_teams_channel_persona(
            db_session=db_session,
            channel_name=channel_config["channel_name"],
            document_set_ids=teams_channel_config_creation_request.document_sets,
            existing_persona_id=None,
        ).id

    teams_channel_config_model = update_teams_channel_config(
        db_session=db_session,
        teams_channel_config_id=teams_channel_config_id,
        persona_id=persona_id,
        channel_config=channel_config,
        standard_answer_category_ids=teams_channel_config_creation_request.standard_answer_categories,
        enable_auto_filters=teams_channel_config_creation_request.enable_auto_filters,
    )
    return TeamsChannelConfig.from_model(teams_channel_config_model)


@router.delete("/admin/teams-app/channel/{teams_channel_config_id}")
def delete_teams_channel_config(
    teams_channel_config_id: int,
    db_session: Session = Depends(get_session),
    _: User | None = Depends(current_admin_user),
) -> None:
    remove_teams_channel_config(
        db_session=db_session,
        teams_channel_config_id=teams_channel_config_id,
    )


@router.post("/admin/teams-app/bots")
def create_bot(
    teams_bot_creation_request: TeamsBotCreationRequest,
    db_session: Session = Depends(get_session),
    _: User | None = Depends(current_admin_user),
) -> TeamsBot:
    tenant_id = get_current_tenant_id()

    teams_bot_model = insert_teams_bot(
        db_session=db_session,
        name=teams_bot_creation_request.name,
        enabled=teams_bot_creation_request.enabled,
        tenant_id=teams_bot_creation_request.tenant_id,
        client_id=teams_bot_creation_request.client_id,
        client_secret=teams_bot_creation_request.client_secret,
    )

    # Create a default Teams channel config
    default_channel_config = ChannelConfig(
        channel_name=None,
        respond_tag_only=True,
    )
    insert_teams_channel_config(
        db_session=db_session,
        teams_bot_id=teams_bot_model.id,
        persona_id=None,
        channel_config=default_channel_config,
        standard_answer_category_ids=[],
        enable_auto_filters=False,
        is_default=True,
    )

    create_milestone_and_report(
        user=None,
        distinct_id=tenant_id or "N/A",
        event_type=MilestoneRecordType.CREATED_ONYX_BOT,
        properties=None,
        db_session=db_session,
    )

    return TeamsBot.from_model(teams_bot_model)


@router.patch("/admin/teams-app/bots/{teams_bot_id}")
def patch_bot(
    teams_bot_id: int,
    teams_bot_creation_request: TeamsBotCreationRequest,
    db_session: Session = Depends(get_session),
    _: User | None = Depends(current_admin_user),
) -> TeamsBot:
    teams_bot_model = update_teams_bot(
        db_session=db_session,
        teams_bot_id=teams_bot_id,
        name=teams_bot_creation_request.name,
        enabled=teams_bot_creation_request.enabled,
        tenant_id=teams_bot_creation_request.tenant_id,
        client_id=teams_bot_creation_request.client_id,
        client_secret=teams_bot_creation_request.client_secret,
    )
    return TeamsBot.from_model(teams_bot_model)


@router.delete("/admin/teams-app/bots/{teams_bot_id}")
def delete_bot(
    teams_bot_id: int,
    db_session: Session = Depends(get_session),
    _: User | None = Depends(current_admin_user),
) -> None:
    remove_teams_bot(
        db_session=db_session,
        teams_bot_id=teams_bot_id,
    )


@router.get("/admin/teams-app/bots")
def list_bots(
    db_session: Session = Depends(get_session),
    _: User | None = Depends(current_admin_user),
) -> list[TeamsBot]:
    teams_bot_models = fetch_teams_bots(db_session=db_session)
    return [
        TeamsBot.from_model(teams_bot_model) for teams_bot_model in teams_bot_models
    ]


@router.get("/admin/teams-app/bots/{bot_id}/config")
def list_bot_configs(
    bot_id: int,
    db_session: Session = Depends(get_session),
    _: User | None = Depends(current_admin_user),
) -> list[TeamsChannelConfig]:
    teams_bot_config_models = fetch_teams_channel_configs(
        db_session=db_session, teams_bot_id=bot_id
    )
    return [
        TeamsChannelConfig.from_model(teams_bot_config_model)
        for teams_bot_config_model in teams_bot_config_models
    ] 