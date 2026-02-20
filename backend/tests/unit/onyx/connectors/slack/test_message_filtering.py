import pytest

from onyx.connectors.slack.connector import _bot_inclusive_msg_filter
from onyx.connectors.slack.connector import default_msg_filter
from onyx.connectors.slack.connector import SlackConnector
from onyx.connectors.slack.connector import SlackMessageFilterReason
from onyx.connectors.slack.models import MessageType


# -- default_msg_filter tests --


@pytest.mark.parametrize(
    "message,expected_reason",
    [
        # Regular user message: not filtered
        (
            {"text": "hello", "user": "U123", "ts": "1.0"},
            None,
        ),
        # Bot message with bot_id: filtered as BOT
        (
            {"text": "automated update", "bot_id": "B123", "ts": "1.0"},
            SlackMessageFilterReason.BOT,
        ),
        # App message with app_id: filtered as BOT
        (
            {"text": "app notification", "app_id": "A123", "ts": "1.0"},
            SlackMessageFilterReason.BOT,
        ),
        # Bot message with both bot_id and app_id: filtered as BOT
        (
            {"text": "bot+app", "bot_id": "B1", "app_id": "A1", "ts": "1.0"},
            SlackMessageFilterReason.BOT,
        ),
        # DanswerBot Testing is explicitly allowed through
        (
            {
                "text": "danswer test",
                "bot_id": "B999",
                "bot_profile": {"name": "DanswerBot Testing"},
                "ts": "1.0",
            },
            None,
        ),
        # channel_join subtype: filtered as DISALLOWED
        (
            {"text": "joined", "subtype": "channel_join", "ts": "1.0"},
            SlackMessageFilterReason.DISALLOWED,
        ),
        # channel_leave subtype: filtered as DISALLOWED
        (
            {"text": "left", "subtype": "channel_leave", "ts": "1.0"},
            SlackMessageFilterReason.DISALLOWED,
        ),
        # pinned_item subtype: filtered as DISALLOWED
        (
            {"text": "pinned", "subtype": "pinned_item", "ts": "1.0"},
            SlackMessageFilterReason.DISALLOWED,
        ),
        # Empty subtype: not filtered
        (
            {"text": "normal", "subtype": "", "ts": "1.0"},
            None,
        ),
    ],
    ids=[
        "regular_user_message",
        "bot_id_message",
        "app_id_message",
        "bot_and_app_id",
        "danswerbot_testing_allowed",
        "channel_join",
        "channel_leave",
        "pinned_item",
        "empty_subtype",
    ],
)
def test_default_msg_filter(
    message: MessageType,
    expected_reason: SlackMessageFilterReason | None,
) -> None:
    assert default_msg_filter(message) == expected_reason


# -- _bot_inclusive_msg_filter tests --


@pytest.mark.parametrize(
    "message,expected_reason",
    [
        # Regular user message: not filtered
        (
            {"text": "hello", "user": "U123", "ts": "1.0"},
            None,
        ),
        # Bot message: NOT filtered (this is the whole point)
        (
            {"text": "automated update", "bot_id": "B123", "ts": "1.0"},
            None,
        ),
        # App message: NOT filtered
        (
            {"text": "app notification", "app_id": "A123", "ts": "1.0"},
            None,
        ),
        # channel_join subtype: still filtered as DISALLOWED
        (
            {"text": "joined", "subtype": "channel_join", "ts": "1.0"},
            SlackMessageFilterReason.DISALLOWED,
        ),
        # channel_leave subtype: still filtered as DISALLOWED
        (
            {"text": "left", "subtype": "channel_leave", "ts": "1.0"},
            SlackMessageFilterReason.DISALLOWED,
        ),
    ],
    ids=[
        "regular_user_message",
        "bot_message_allowed",
        "app_message_allowed",
        "channel_join_still_filtered",
        "channel_leave_still_filtered",
    ],
)
def test_bot_inclusive_msg_filter(
    message: MessageType,
    expected_reason: SlackMessageFilterReason | None,
) -> None:
    assert _bot_inclusive_msg_filter(message) == expected_reason


# -- SlackConnector config tests --


def test_default_filter_when_include_bot_messages_false() -> None:
    """When include_bot_messages is False (default), the default filter is used."""
    connector = SlackConnector(use_redis=False)
    assert connector.msg_filter_func is default_msg_filter


def test_bot_inclusive_filter_when_include_bot_messages_true() -> None:
    """When include_bot_messages is True, the bot-inclusive filter is used."""
    connector = SlackConnector(include_bot_messages=True, use_redis=False)
    assert connector.msg_filter_func is _bot_inclusive_msg_filter


def test_include_bot_messages_defaults_to_false() -> None:
    """The include_bot_messages config defaults to False for backward compatibility."""
    connector = SlackConnector(use_redis=False)
    assert connector.include_bot_messages is False
