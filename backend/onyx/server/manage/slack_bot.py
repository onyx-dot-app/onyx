from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from sqlalchemy.orm import Session

from onyx.auth.users import current_admin_user
from onyx.configs.constants import MilestoneRecordType
from onyx.db.constants import SLACK_BOT_PERSONA_PREFIX
from onyx.db.engine.sql_engine import get_session
from onyx.db.models import ChannelConfig
from onyx.db.models import User
from onyx.db.persona import get_persona_by_id
from onyx.db.slack_bot import fetch_slack_bot
from onyx.db.slack_bot import fetch_slack_bots
from onyx.db.slack_bot import insert_slack_bot
from onyx.db.slack_bot import remove_slack_bot
from onyx.db.slack_bot import update_slack_bot
from onyx.db.slack_channel_config import create_slack_channel_persona
from onyx.db.slack_channel_config import fetch_slack_channel_config
from onyx.db.slack_channel_config import fetch_slack_channel_configs
from onyx.db.slack_channel_config import insert_slack_channel_config
from onyx.db.slack_channel_config import remove_slack_channel_config
from onyx.db.slack_channel_config import update_slack_channel_config
from onyx.onyxbot.slack.config import validate_channel_name
from onyx.server.manage.models import SlackBot
from onyx.server.manage.models import SlackBotCreationRequest
from onyx.server.manage.models import SlackChannelConfig
from onyx.server.manage.models import SlackChannelConfigCreationRequest
from onyx.server.manage.validate_tokens import validate_app_token
from onyx.server.manage.validate_tokens import validate_bot_token
from onyx.server.manage.validate_tokens import validate_user_token
from onyx.utils.logger import setup_logger
from onyx.utils.telemetry import create_milestone_and_report
from shared_configs.contextvars import get_current_tenant_id

SLACK_API_CHANNELS_PER_PAGE = 100
SLACK_MAX_RETURNED_CHANNELS = 500

logger = setup_logger()


router = APIRouter(prefix="/manage")


def _form_channel_config(
    db_session: Session,
    slack_channel_config_creation_request: SlackChannelConfigCreationRequest,
    current_slack_channel_config_id: int | None,
) -> ChannelConfig:
    raw_channel_name = slack_channel_config_creation_request.channel_name
    respond_tag_only = slack_channel_config_creation_request.respond_tag_only
    respond_member_group_list = (
        slack_channel_config_creation_request.respond_member_group_list
    )
    answer_filters = slack_channel_config_creation_request.answer_filters
    follow_up_tags = slack_channel_config_creation_request.follow_up_tags

    try:
        cleaned_channel_name = validate_channel_name(
            db_session=db_session,
            channel_name=raw_channel_name,
            current_slack_channel_config_id=current_slack_channel_config_id,
            current_slack_bot_id=slack_channel_config_creation_request.slack_bot_id,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=str(e),
        )

    if respond_tag_only and respond_member_group_list:
        raise ValueError(
            "Cannot set OnyxBot to only respond to tags only and "
            "also respond to a predetermined set of users."
        )

    if (
        slack_channel_config_creation_request.is_ephemeral
        and slack_channel_config_creation_request.respond_member_group_list
    ):
        raise ValueError(
            "Cannot set OnyxBot to respond to users in a private (ephemeral) message "
            "and also respond to a selected list of users."
        )

    channel_config: ChannelConfig = {
        "channel_name": cleaned_channel_name,
    }
    if respond_tag_only is not None:
        channel_config["respond_tag_only"] = respond_tag_only
    if respond_member_group_list:
        channel_config["respond_member_group_list"] = respond_member_group_list
    if answer_filters:
        channel_config["answer_filters"] = answer_filters
    if follow_up_tags is not None:
        channel_config["follow_up_tags"] = follow_up_tags

    channel_config["show_continue_in_web_ui"] = (
        slack_channel_config_creation_request.show_continue_in_web_ui
    )

    channel_config["respond_to_bots"] = (
        slack_channel_config_creation_request.respond_to_bots
    )

    channel_config["is_ephemeral"] = slack_channel_config_creation_request.is_ephemeral

    channel_config["disabled"] = slack_channel_config_creation_request.disabled

    return channel_config


@router.post("/admin/slack-app/channel")
def create_slack_channel_config(
    slack_channel_config_creation_request: SlackChannelConfigCreationRequest,
    db_session: Session = Depends(get_session),
    _: User | None = Depends(current_admin_user),
) -> SlackChannelConfig:
    channel_config = _form_channel_config(
        db_session=db_session,
        slack_channel_config_creation_request=slack_channel_config_creation_request,
        current_slack_channel_config_id=None,
    )

    if channel_config["channel_name"] is None:
        raise HTTPException(
            status_code=400,
            detail="Channel name is required",
        )

    persona_id = None
    if slack_channel_config_creation_request.persona_id is not None:
        persona_id = slack_channel_config_creation_request.persona_id
    elif slack_channel_config_creation_request.document_sets:
        persona_id = create_slack_channel_persona(
            db_session=db_session,
            channel_name=channel_config["channel_name"],
            document_set_ids=slack_channel_config_creation_request.document_sets,
            existing_persona_id=None,
        ).id

    slack_channel_config_model = insert_slack_channel_config(
        db_session=db_session,
        slack_bot_id=slack_channel_config_creation_request.slack_bot_id,
        persona_id=persona_id,
        channel_config=channel_config,
        standard_answer_category_ids=slack_channel_config_creation_request.standard_answer_categories,
        enable_auto_filters=slack_channel_config_creation_request.enable_auto_filters,
    )
    return SlackChannelConfig.from_model(slack_channel_config_model)


@router.patch("/admin/slack-app/channel/{slack_channel_config_id}")
def patch_slack_channel_config(
    slack_channel_config_id: int,
    slack_channel_config_creation_request: SlackChannelConfigCreationRequest,
    db_session: Session = Depends(get_session),
    _: User | None = Depends(current_admin_user),
) -> SlackChannelConfig:
    channel_config = _form_channel_config(
        db_session=db_session,
        slack_channel_config_creation_request=slack_channel_config_creation_request,
        current_slack_channel_config_id=slack_channel_config_id,
    )

    persona_id = None
    if slack_channel_config_creation_request.persona_id is not None:
        persona_id = slack_channel_config_creation_request.persona_id
    elif slack_channel_config_creation_request.document_sets:
        existing_slack_channel_config = fetch_slack_channel_config(
            db_session=db_session, slack_channel_config_id=slack_channel_config_id
        )
        if existing_slack_channel_config is None:
            raise HTTPException(
                status_code=404,
                detail="Slack channel config not found",
            )

        existing_persona_id = existing_slack_channel_config.persona_id
        if existing_persona_id is not None:
            persona = get_persona_by_id(
                persona_id=existing_persona_id,
                user=None,
                db_session=db_session,
                is_for_edit=False,
            )

            if not persona.name.startswith(SLACK_BOT_PERSONA_PREFIX):
                # Don't update actual non-slackbot specific personas
                # Since this one specified document sets, we have to create a new persona
                # for this OnyxBot config
                existing_persona_id = None
            else:
                existing_persona_id = existing_slack_channel_config.persona_id

        persona_id = create_slack_channel_persona(
            db_session=db_session,
            channel_name=channel_config["channel_name"],
            document_set_ids=slack_channel_config_creation_request.document_sets,
            existing_persona_id=existing_persona_id,
            enable_auto_filters=slack_channel_config_creation_request.enable_auto_filters,
        ).id

    slack_channel_config_model = update_slack_channel_config(
        db_session=db_session,
        slack_channel_config_id=slack_channel_config_id,
        persona_id=persona_id,
        channel_config=channel_config,
        standard_answer_category_ids=slack_channel_config_creation_request.standard_answer_categories,
        enable_auto_filters=slack_channel_config_creation_request.enable_auto_filters,
        disabled=slack_channel_config_creation_request.disabled,
    )
    return SlackChannelConfig.from_model(slack_channel_config_model)


@router.delete("/admin/slack-app/channel/{slack_channel_config_id}")
def delete_slack_channel_config(
    slack_channel_config_id: int,
    db_session: Session = Depends(get_session),
    user: User | None = Depends(current_admin_user),
) -> None:
    remove_slack_channel_config(
        db_session=db_session,
        slack_channel_config_id=slack_channel_config_id,
        user=user,
    )


@router.get("/admin/slack-app/channel")
def list_slack_channel_configs(
    db_session: Session = Depends(get_session),
    _: User | None = Depends(current_admin_user),
) -> list[SlackChannelConfig]:
    slack_channel_config_models = fetch_slack_channel_configs(db_session=db_session)
    return [
        SlackChannelConfig.from_model(slack_channel_config_model)
        for slack_channel_config_model in slack_channel_config_models
    ]


@router.post("/admin/slack-app/bots")
def create_bot(
    slack_bot_creation_request: SlackBotCreationRequest,
    db_session: Session = Depends(get_session),
    _: User | None = Depends(current_admin_user),
) -> SlackBot:
    tenant_id = get_current_tenant_id()

    validate_app_token(slack_bot_creation_request.app_token)
    validate_bot_token(slack_bot_creation_request.bot_token)
    validate_user_token(slack_bot_creation_request.user_token)

    slack_bot_model = insert_slack_bot(
        db_session=db_session,
        name=slack_bot_creation_request.name,
        enabled=slack_bot_creation_request.enabled,
        bot_token=slack_bot_creation_request.bot_token,
        app_token=slack_bot_creation_request.app_token,
        user_token=slack_bot_creation_request.user_token,
    )

    # Create a default Slack channel config
    default_channel_config = ChannelConfig(
        channel_name=None,
        respond_tag_only=True,
    )
    insert_slack_channel_config(
        db_session=db_session,
        slack_bot_id=slack_bot_model.id,
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

    return SlackBot.from_model(slack_bot_model)


@router.patch("/admin/slack-app/bots/{slack_bot_id}")
def patch_bot(
    slack_bot_id: int,
    slack_bot_creation_request: SlackBotCreationRequest,
    db_session: Session = Depends(get_session),
    _: User | None = Depends(current_admin_user),
) -> SlackBot:
    validate_bot_token(slack_bot_creation_request.bot_token)
    validate_app_token(slack_bot_creation_request.app_token)
    validate_user_token(slack_bot_creation_request.user_token)
    slack_bot_model = update_slack_bot(
        db_session=db_session,
        slack_bot_id=slack_bot_id,
        name=slack_bot_creation_request.name,
        enabled=slack_bot_creation_request.enabled,
        bot_token=slack_bot_creation_request.bot_token,
        app_token=slack_bot_creation_request.app_token,
        user_token=slack_bot_creation_request.user_token,
    )
    return SlackBot.from_model(slack_bot_model)


@router.delete("/admin/slack-app/bots/{slack_bot_id}")
def delete_bot(
    slack_bot_id: int,
    db_session: Session = Depends(get_session),
    _: User | None = Depends(current_admin_user),
) -> None:
    remove_slack_bot(
        db_session=db_session,
        slack_bot_id=slack_bot_id,
    )


@router.get("/admin/slack-app/bots/{slack_bot_id}")
def get_bot_by_id(
    slack_bot_id: int,
    db_session: Session = Depends(get_session),
    _: User | None = Depends(current_admin_user),
) -> SlackBot:
    slack_bot_model = fetch_slack_bot(
        db_session=db_session,
        slack_bot_id=slack_bot_id,
    )
    return SlackBot.from_model(slack_bot_model)


@router.get("/admin/slack-app/bots")
def list_bots(
    db_session: Session = Depends(get_session),
    _: User | None = Depends(current_admin_user),
) -> list[SlackBot]:
    slack_bot_models = fetch_slack_bots(db_session=db_session)
    return [
        SlackBot.from_model(slack_bot_model) for slack_bot_model in slack_bot_models
    ]


@router.get("/admin/slack-app/bots/{bot_id}/config")
def list_bot_configs(
    bot_id: int,
    db_session: Session = Depends(get_session),
    _: User | None = Depends(current_admin_user),
) -> list[SlackChannelConfig]:
    slack_bot_config_models = fetch_slack_channel_configs(
        db_session=db_session, slack_bot_id=bot_id
    )
    return [
        SlackChannelConfig.from_model(slack_bot_config_model)
        for slack_bot_config_model in slack_bot_config_models
    ]
