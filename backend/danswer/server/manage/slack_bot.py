from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from sqlalchemy.orm import Session

from danswer.auth.users import current_admin_user
from danswer.danswerbot.slack.config import validate_channel_names
from danswer.danswerbot.slack.tokens import fetch_tokens
from danswer.danswerbot.slack.tokens import save_tokens
from danswer.db.chat import get_persona_by_id
from danswer.db.constants import SLACK_BOT_PERSONA_PREFIX
from danswer.db.engine import get_session
from danswer.db.models import ChannelConfig
from danswer.db.models import User
from danswer.db.slack_bot_config import create_slack_bot_persona
from danswer.db.slack_bot_config import fetch_slack_bot_config
from danswer.db.slack_bot_config import fetch_slack_bot_configs
from danswer.db.slack_bot_config import insert_slack_bot_config
from danswer.db.slack_bot_config import remove_slack_bot_config
from danswer.db.slack_bot_config import update_slack_bot_config
from danswer.dynamic_configs.interface import ConfigNotFoundError
from danswer.server.manage.models import SlackBotConfig
from danswer.server.manage.models import SlackBotConfigCreationRequest
from danswer.server.manage.models import SlackBotTokens


router = APIRouter(prefix="/manage")


def _form_channel_config(
    slack_bot_config_creation_request: SlackBotConfigCreationRequest,
    current_slack_bot_config_id: int | None,
    db_session: Session,
) -> ChannelConfig:
    raw_channel_names = slack_bot_config_creation_request.channel_names
    respond_tag_only = slack_bot_config_creation_request.respond_tag_only
    respond_team_member_list = (
        slack_bot_config_creation_request.respond_team_member_list
    )
    answer_filters = slack_bot_config_creation_request.answer_filters
    follow_up_tags = slack_bot_config_creation_request.follow_up_tags

    if not raw_channel_names:
        raise HTTPException(
            status_code=400,
            detail="Must provide at least one channel name",
        )

    try:
        cleaned_channel_names = validate_channel_names(
            channel_names=raw_channel_names,
            current_slack_bot_config_id=current_slack_bot_config_id,
            db_session=db_session,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=str(e),
        )

    if respond_tag_only and respond_team_member_list:
        raise ValueError(
            "Cannot set DanswerBot to only respond to tags only and "
            "also respond to a predetermined set of users."
        )

    channel_config: ChannelConfig = {
        "channel_names": cleaned_channel_names,
    }
    if respond_tag_only is not None:
        channel_config["respond_tag_only"] = respond_tag_only
    if respond_team_member_list:
        channel_config["respond_team_member_list"] = respond_team_member_list
    if answer_filters:
        channel_config["answer_filters"] = answer_filters
    if follow_up_tags is not None:
        channel_config["follow_up_tags"] = follow_up_tags

    channel_config[
        "respond_to_bots"
    ] = slack_bot_config_creation_request.respond_to_bots

    return channel_config


@router.post("/admin/slack-bot/config")
def create_slack_bot_config(
    slack_bot_config_creation_request: SlackBotConfigCreationRequest,
    db_session: Session = Depends(get_session),
    _: User | None = Depends(current_admin_user),
) -> SlackBotConfig:
    channel_config = _form_channel_config(
        slack_bot_config_creation_request, None, db_session
    )

    persona_id = None
    if slack_bot_config_creation_request.persona_id is not None:
        persona_id = slack_bot_config_creation_request.persona_id
    elif slack_bot_config_creation_request.document_sets:
        persona_id = create_slack_bot_persona(
            db_session=db_session,
            channel_names=channel_config["channel_names"],
            document_set_ids=slack_bot_config_creation_request.document_sets,
            existing_persona_id=None,
        ).id

    slack_bot_config_model = insert_slack_bot_config(
        persona_id=persona_id,
        channel_config=channel_config,
        response_type=slack_bot_config_creation_request.response_type,
        db_session=db_session,
    )
    return SlackBotConfig.from_model(slack_bot_config_model)


@router.patch("/admin/slack-bot/config/{slack_bot_config_id}")
def patch_slack_bot_config(
    slack_bot_config_id: int,
    slack_bot_config_creation_request: SlackBotConfigCreationRequest,
    db_session: Session = Depends(get_session),
    _: User | None = Depends(current_admin_user),
) -> SlackBotConfig:
    channel_config = _form_channel_config(
        slack_bot_config_creation_request, slack_bot_config_id, db_session
    )

    persona_id = None
    if slack_bot_config_creation_request.persona_id is not None:
        persona_id = slack_bot_config_creation_request.persona_id
    elif slack_bot_config_creation_request.document_sets:
        existing_slack_bot_config = fetch_slack_bot_config(
            db_session=db_session, slack_bot_config_id=slack_bot_config_id
        )
        if existing_slack_bot_config is None:
            raise HTTPException(
                status_code=404,
                detail="Slack bot config not found",
            )

        existing_persona_id = existing_slack_bot_config.persona_id
        if existing_persona_id is not None:
            persona = get_persona_by_id(
                persona_id=existing_persona_id, user=None, db_session=db_session
            )

            if not persona.name.startswith(SLACK_BOT_PERSONA_PREFIX):
                # Don't update actual non-slackbot specific personas
                # Since this one specified document sets, we have to create a new persona
                # for this DanswerBot config
                existing_persona_id = None
            else:
                existing_persona_id = existing_slack_bot_config.persona_id

        persona_id = create_slack_bot_persona(
            db_session=db_session,
            channel_names=channel_config["channel_names"],
            document_set_ids=slack_bot_config_creation_request.document_sets,
            existing_persona_id=existing_persona_id,
        ).id

    slack_bot_config_model = update_slack_bot_config(
        slack_bot_config_id=slack_bot_config_id,
        persona_id=persona_id,
        channel_config=channel_config,
        response_type=slack_bot_config_creation_request.response_type,
        db_session=db_session,
    )
    return SlackBotConfig.from_model(slack_bot_config_model)


@router.delete("/admin/slack-bot/config/{slack_bot_config_id}")
def delete_slack_bot_config(
    slack_bot_config_id: int,
    db_session: Session = Depends(get_session),
    _: User | None = Depends(current_admin_user),
) -> None:
    remove_slack_bot_config(
        slack_bot_config_id=slack_bot_config_id, db_session=db_session
    )


@router.get("/admin/slack-bot/config")
def list_slack_bot_configs(
    db_session: Session = Depends(get_session),
    _: User | None = Depends(current_admin_user),
) -> list[SlackBotConfig]:
    slack_bot_config_models = fetch_slack_bot_configs(db_session=db_session)
    return [
        SlackBotConfig.from_model(slack_bot_config_model)
        for slack_bot_config_model in slack_bot_config_models
    ]


@router.put("/admin/slack-bot/tokens")
def put_tokens(
    tokens: SlackBotTokens,
    _: User | None = Depends(current_admin_user),
) -> None:
    save_tokens(tokens=tokens)


@router.get("/admin/slack-bot/tokens")
def get_tokens(_: User | None = Depends(current_admin_user)) -> SlackBotTokens:
    try:
        return fetch_tokens()
    except ConfigNotFoundError:
        raise HTTPException(status_code=404, detail="No tokens found")
