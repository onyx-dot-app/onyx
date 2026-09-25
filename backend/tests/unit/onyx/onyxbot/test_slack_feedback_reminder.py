from unittest.mock import MagicMock

import pytest
from slack_sdk import WebClient

from onyx.onyxbot.slack.handlers.handle_message import schedule_feedback_reminder
from onyx.onyxbot.slack.models import SlackMessageInfo, ThreadMessage


def _make_message_info() -> SlackMessageInfo:
    return SlackMessageInfo(
        thread_messages=[ThreadMessage(message="A question?")],
        channel_to_respond="C123",
        msg_to_respond="123.456",
        thread_to_respond="123.456",
        sender_id="U123",
        email="user@example.com",
        bypass_filters=False,
        is_slash_command=False,
        is_bot_dm=False,
    )


def test_feedback_reminder_is_not_scheduled_when_feedback_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "onyx.onyxbot.slack.handlers.handle_message.ONYX_BOT_FEEDBACK_REMINDER",
        10,
    )
    client = MagicMock(spec=WebClient)

    reminder_id = schedule_feedback_reminder(
        details=_make_message_info(),
        include_followup=False,
        client=client,
        feedback_enabled=False,
    )

    assert reminder_id is None
    assert client.mock_calls == []
