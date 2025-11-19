import datetime

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from onyx.configs.onyxbot_configs import ONYX_BOT_FEEDBACK_REMINDER
from onyx.configs.onyxbot_configs import ONYX_BOT_REACT_EMOJI
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import SlackChannelConfig
from onyx.db.users import add_slack_user_if_not_exists
from onyx.onyxbot.slack.blocks import get_feedback_reminder_blocks
from onyx.onyxbot.slack.handlers.handle_regular_answer import (
    handle_regular_answer,
)
from onyx.onyxbot.slack.handlers.handle_standard_answers import (
    handle_standard_answers,
)
from onyx.onyxbot.slack.models import SlackMessageInfo
from onyx.onyxbot.slack.utils import fetch_slack_user_ids_from_emails
from onyx.onyxbot.slack.utils import fetch_user_ids_from_groups
from onyx.onyxbot.slack.utils import respond_in_thread_or_channel
from onyx.onyxbot.slack.utils import slack_usage_report
from onyx.onyxbot.slack.utils import update_emote_react
from onyx.utils.logger import setup_logger
from shared_configs.configs import SLACK_CHANNEL_ID

logger_base = setup_logger()


def send_msg_ack_to_user(details: SlackMessageInfo, client: WebClient) -> None:
    if details.is_slash_command and details.sender_id:
        respond_in_thread_or_channel(
            client=client,
            channel=details.channel_to_respond,
            thread_ts=details.msg_to_respond,
            receiver_ids=[details.sender_id],
            text="Hi, we're evaluating your query :face_with_monocle:",
        )
        return

    update_emote_react(
        emoji=ONYX_BOT_REACT_EMOJI,
        channel=details.channel_to_respond,
        message_ts=details.msg_to_respond,
        remove=False,
        client=client,
    )


def schedule_feedback_reminder(
    details: SlackMessageInfo, include_followup: bool, client: WebClient
) -> str | None:
    logger = setup_logger(extra={SLACK_CHANNEL_ID: details.channel_to_respond})

    if not ONYX_BOT_FEEDBACK_REMINDER:
        logger.info("Scheduled feedback reminder disabled...")
        return None

    try:
        permalink = client.chat_getPermalink(
            channel=details.channel_to_respond,
            message_ts=details.msg_to_respond,  # type:ignore
        )
    except SlackApiError as e:
        logger.error(f"Unable to generate the feedback reminder permalink: {e}")
        return None

    now = datetime.datetime.now()
    future = now + datetime.timedelta(minutes=ONYX_BOT_FEEDBACK_REMINDER)

    try:
        response = client.chat_scheduleMessage(
            channel=details.sender_id,  # type:ignore
            post_at=int(future.timestamp()),
            blocks=[
                get_feedback_reminder_blocks(
                    thread_link=permalink.data["permalink"],  # type:ignore
                    include_followup=include_followup,
                )
            ],
            text="",
        )
        logger.info("Scheduled feedback reminder configured")
        return response.data["scheduled_message_id"]  # type:ignore
    except SlackApiError as e:
        logger.error(f"Unable to generate the feedback reminder message: {e}")
        return None


def remove_scheduled_feedback_reminder(
    client: WebClient, channel: str | None, msg_id: str
) -> None:
    logger = setup_logger(extra={SLACK_CHANNEL_ID: channel})

    try:
        client.chat_deleteScheduledMessage(
            channel=channel, scheduled_message_id=msg_id  # type:ignore
        )
        logger.info("Scheduled feedback reminder deleted")
    except SlackApiError as e:
        if e.response["error"] == "invalid_scheduled_message_id":
            logger.info(
                "Unable to delete the scheduled message. It must have already been posted"
            )


def handle_message(
    message_info: SlackMessageInfo,
    slack_channel_config: SlackChannelConfig,
    client: WebClient,
    feedback_reminder_id: str | None,
) -> bool:
    """Potentially respond to the user message depending on filters and if an answer was generated

    Returns True if need to respond with an additional message to the user(s) after this
    function is finished. True indicates an unexpected failure that needs to be communicated
    Query thrown out by filters due to config does not count as a failure that should be notified
    Onyx failing to answer/retrieve docs does count and should be notified
    """
    channel = message_info.channel_to_respond

    logger = setup_logger(extra={SLACK_CHANNEL_ID: channel})

    messages = message_info.thread_messages
    sender_id = message_info.sender_id
    bypass_filters = message_info.bypass_filters
    is_slash_command = message_info.is_slash_command
    is_bot_dm = message_info.is_bot_dm

    action = "slack_message"
    if is_slash_command:
        action = "slack_slash_message"
    elif bypass_filters:
        action = "slack_tag_message"
    elif is_bot_dm:
        action = "slack_dm_message"
    slack_usage_report(action=action, sender_id=sender_id, client=client)

    document_set_names: list[str] | None = None
    persona = slack_channel_config.persona if slack_channel_config else None
    if persona:
        document_set_names = [
            document_set.name for document_set in persona.document_sets
        ]

    respond_tag_only = False
    respond_member_group_list = None

    channel_conf = None
    if slack_channel_config and slack_channel_config.channel_config:
        channel_conf = slack_channel_config.channel_config
        if not bypass_filters and "answer_filters" in channel_conf:
            if (
                "questionmark_prefilter" in channel_conf["answer_filters"]
                and "?" not in messages[-1].message
            ):
                logger.info(
                    "Skipping message since it does not contain a question mark"
                )
                return False

        logger.info(
            "Found slack bot config for channel. Restricting bot to use document "
            f"sets: {document_set_names}, "
            f"validity checks enabled: {channel_conf.get('answer_filters', 'NA')}"
        )

        respond_tag_only = channel_conf.get("respond_tag_only") or False
        respond_member_group_list = channel_conf.get("respond_member_group_list", None)

    # Only default config can be disabled.
    # If channel config is disabled, bot should not respond to this message (including DMs)
    if slack_channel_config.channel_config.get("disabled"):
        logger.info("Skipping message: OnyxBot is disabled for this channel")
        return False

    # If bot should only respond to tags and is not tagged nor in a DM, skip message
    if respond_tag_only and not bypass_filters and not is_bot_dm:
        logger.info("Skipping message: OnyxBot only responds to tags in this channel")
        return False

    # List of user id to send message to, if None, send to everyone in channel
    send_to: list[str] | None = None
    missing_users: list[str] | None = None
    if respond_member_group_list:
        send_to, missing_ids = fetch_slack_user_ids_from_emails(
            respond_member_group_list, client
        )

        user_ids, missing_users = fetch_user_ids_from_groups(missing_ids, client)
        send_to = list(set(send_to + user_ids)) if send_to else user_ids

        if missing_users:
            logger.warning(f"Failed to find these users/groups: {missing_users}")

    # If configured to respond to team members only, then cannot be used with a /OnyxBot command
    # which would just respond to the sender
    if send_to and is_slash_command:
        if sender_id:
            respond_in_thread_or_channel(
                client=client,
                channel=channel,
                receiver_ids=[sender_id],
                text="The OnyxBot slash command is not enabled for this channel",
                thread_ts=None,
            )

    try:
        send_msg_ack_to_user(message_info, client)
    except SlackApiError as e:
        logger.error(f"Was not able to react to user message due to: {e}")

    with get_session_with_current_tenant() as db_session:
        if message_info.email:
            add_slack_user_if_not_exists(db_session, message_info.email)

        # first check if we need to respond with a standard answer
        # standard answers should be published in a thread
        used_standard_answer = handle_standard_answers(
            message_info=message_info,
            receiver_ids=send_to,
            slack_channel_config=slack_channel_config,
            logger=logger,
            client=client,
            db_session=db_session,
        )
        if used_standard_answer:
            return False

        # if no standard answer applies, try a regular answer
        issue_with_regular_answer = handle_regular_answer(
            message_info=message_info,
            slack_channel_config=slack_channel_config,
            receiver_ids=send_to,
            client=client,
            channel=channel,
            logger=logger,
            feedback_reminder_id=feedback_reminder_id,
        )
        return issue_with_regular_answer
