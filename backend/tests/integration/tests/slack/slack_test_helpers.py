from typing import Any

from slack_sdk import WebClient

from onyx.db.chat import get_chat_messages_by_session
from onyx.db.models import ChatSession
from onyx.db.models import User
from onyx.utils.logger import setup_logger
from tests.integration.common_utils.managers.slack import SlackManager
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.tests.slack.constants import PRIMARY_USER_EMAIL
from tests.integration.tests.slack.constants import SHORT_REPLY_TIMEOUT
from tests.integration.tests.slack.utils import list_slack_channel_configs
from tests.integration.tests.slack.utils import update_slack_channel_config

logger = setup_logger()


def send_and_receive_dm(
    slack_bot_client: WebClient,
    slack_user_client: WebClient,
    message: str,
    timeout_secs: int = 200,
) -> Any:
    """Sends a direct message (DM) from a user to the Onyx bot and waits for a reply."""
    user_id, bot_id = SlackManager.get_client_user_and_bot_ids(slack_bot_client)
    logger.info(f"Slack bot user ID: {user_id}, Slack bot ID: {bot_id}")

    # Open DM channel with the bot
    channel = SlackManager.get_dm_channel(slack_user_client, user_id)
    logger.info(f"Opened DM channel {channel} with bot {bot_id}")

    # Post a message as the user
    # This message is sent to the bot, not the channel
    original_msg_ts = SlackManager.add_message_to_channel(
        slack_user_client, channel=channel, message=message
    )
    logger.info(f"Posted message to channel {channel}")

    # Wait for the bot to respond
    reply = SlackManager.poll_for_reply(
        slack_user_client,
        channel=channel,
        original_message_ts=original_msg_ts,
        timeout_seconds=timeout_secs,
    )
    logger.info(f"Received message from bot: {reply}")

    return reply


def send_dm_with_optional_timeout(
    slack_bot_client: WebClient,
    slack_user_client: WebClient,
    message_text: str,
    expected_text: str = None,
):
    """Sends a DM and receives a reply, using a shorter timeout if no specific reply text is expected."""
    if expected_text is None:
        return send_and_receive_dm(
            slack_bot_client,
            slack_user_client,
            message_text,
            timeout_secs=SHORT_REPLY_TIMEOUT,
        )
    else:
        return send_and_receive_dm(slack_bot_client, slack_user_client, message_text)


def send_channel_msg_with_optional_timeout(
    slack_bot_client: WebClient,
    slack_user_client: WebClient,
    message_text: str,
    channel: dict[str, Any],
    tag_bot: bool = False,
    expected_text: str = None,
):
    """Sends a channel message and receives a reply, using a shorter timeout if no specific reply text is expected."""

    if expected_text is None:
        return send_and_receive_channel_message(
            slack_user_client=slack_user_client,
            slack_bot_client=slack_bot_client,
            message=message_text,
            channel=channel,
            tag_bot=tag_bot,
            timeout_secs=SHORT_REPLY_TIMEOUT,
        )
    else:
        return send_and_receive_channel_message(
            slack_user_client=slack_user_client,
            slack_bot_client=slack_bot_client,
            message=message_text,
            channel=channel,
            tag_bot=tag_bot,
        )


def send_message_to_channel(
    slack_user_client: WebClient,
    slack_bot_client: WebClient,
    message: str,
    channel: dict[str, Any],
    tag_bot: bool = False,
) -> str:
    """Sends a message to a specified Slack channel as the user."""
    user_id, _ = SlackManager.get_client_user_and_bot_ids(slack_bot_client)
    logger.info(f"Slack bot user ID: {user_id}")

    # tag the bot in the message if required
    if tag_bot:
        message = f"<@{user_id}> {message}"

    logger.info(f"Sending message to channel {channel['name']}: {message}")
    # Post a message as the user
    original_msg_ts = SlackManager.add_message_to_channel(
        slack_user_client, channel=channel, message=message
    )
    logger.info(f"Posted message to channel {channel['name']}")
    return original_msg_ts


def send_and_receive_channel_message(
    slack_user_client: WebClient,
    slack_bot_client: WebClient,
    message: str,
    channel: dict[str, Any],
    tag_bot: bool = False,
    timeout_secs: int = 200,
) -> Any:
    """Sends a message to a channel and waits for the bot's reply."""
    original_msg_ts = send_message_to_channel(
        slack_user_client,
        slack_bot_client,
        message=message,
        channel=channel,
        tag_bot=tag_bot,
    )
    # Wait for the bot to respond
    reply = SlackManager.poll_for_reply(
        slack_user_client,
        channel=channel,
        original_message_ts=original_msg_ts,
        timeout_seconds=timeout_secs,
    )
    logger.info(f"Received message from bot: {reply}")
    return reply


def update_channel_config(
    bot_id: str,
    user_performing_action: DATestUser,
    channel_name: str | None = None,
    updated_config_data: dict[str, Any] = {},
) -> dict[str, Any]:
    """Updates the configuration for a specific Slack channel or the default channel."""
    # Get all channel configs
    channel_configs = list_slack_channel_configs(
        bot_id=bot_id, user_performing_action=user_performing_action
    )
    logger.info(f"Channel configs: {channel_configs}")

    for channel_config in channel_configs:
        inner_channel_config = channel_config["channel_config"]
        channel_name_from_config = inner_channel_config["channel_name"]
        logger.info(f"Channel name: {channel_name_from_config} | {channel_name}")
        if channel_name is None and channel_config["is_default"]:
            channel_config_id = channel_config.get("id")
            channel_name = channel_config.get("channel_name")
            logger.info(f"Found default channel config ID: {channel_config_id}")
            break
        elif inner_channel_config.get("channel_name") == channel_name:
            channel_config_id = channel_config.get("id")
            logger.info(f"Found channel config ID: {channel_config_id}")
            break
    else:
        logger.error("No channel config found.")
        raise ValueError("No channel config found.")

    logger.info(f"Channel config ID: {channel_config_id}")

    channel_config = {
        "slack_bot_id": bot_id,
        "channel_name": channel_name or "None",
        "respond_tag_only": True,
        "response_type": "citations",
    }

    channel_config_to_update = {**channel_config, **updated_config_data}
    logger.info(f"Channel config to update: {channel_config_to_update}")

    # Update the channel config
    updated_channel_config = update_slack_channel_config(
        config_id=channel_config_id,
        user_performing_action=user_performing_action,
        update_data=channel_config_to_update,
    )

    logger.info(f"Updated channel config: {updated_channel_config}")
    return updated_channel_config


def assert_button_presence(
    blocks: list[dict[str, Any]],
    action_id: str,
    should_exist: bool,
    test_name: str,
    channel_name: str = "DM",
):
    """Asserts the presence or absence of a button with a specific action_id within Slack message blocks."""
    found_button = False
    for block in blocks:
        if block["type"] == "actions":
            for element in block.get("elements", []):
                if (
                    element.get("type") == "button"
                    and element.get("action_id") == action_id
                ):
                    found_button = True
                    break
            if found_button:
                break
    if should_exist:
        assert found_button, f"{test_name}: Button should be present in {channel_name}"
    else:
        assert (
            not found_button
        ), f"{test_name}: Button should NOT be present in {channel_name}"


def get_last_chat_session_and_messages(user_id, db_session):
    """
    Queries the last created chat session for the given user and returns its messages.
    """
    # Get all chat sessions for the user, ordered by time_updated descending
    chat_sessions = (
        db_session.query(ChatSession)
        .filter(ChatSession.user_id == user_id)
        .order_by(ChatSession.time_updated.desc())
        .all()
    )
    logger.info(f"Chat sessions: {chat_sessions}")
    if not chat_sessions:
        logger.warning("No chat sessions found for the user.")
        return None, []

    last_session = chat_sessions[0]
    messages = get_chat_messages_by_session(
        chat_session_id=last_session.id,
        user_id=user_id,
        db_session=db_session,
    )
    logger.info(f"Retrieved messages: {messages}")
    return last_session, messages


def get_primary_user_record(db_session):
    """
    Returns the first user record where role is 'SLACK_USER'.
    """
    return db_session.query(User).filter(User.email == PRIMARY_USER_EMAIL).first()
