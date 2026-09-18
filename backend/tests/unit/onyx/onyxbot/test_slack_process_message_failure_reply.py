"""An unexpected failure still gets a notice when the sender addressed the bot."""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from slack_sdk.errors import SlackApiError

from onyx.onyxbot.slack.handlers.handle_regular_answer import (
    SLACK_ANSWER_FAILED_MESSAGE,
)
from onyx.onyxbot.slack.listener import process_message

_LISTENER = "onyx.onyxbot.slack.listener"
_HANDLERS = "onyx.onyxbot.slack.handlers.handle_regular_answer"


def _event_request(event: dict[str, Any]) -> MagicMock:
    req = MagicMock()
    req.type = "events_api"
    req.payload = {"event": event}
    return req


def _slash_request() -> MagicMock:
    req = MagicMock()
    req.type = "slash_commands"
    req.payload = {"channel_id": "C123", "user_id": "U123", "text": "question"}
    return req


_TAGGED: dict[str, Any] = {"type": "app_mention", "channel": "C123", "ts": "111.222"}
_DM: dict[str, Any] = {
    "type": "message",
    "channel_type": "im",
    "channel": "D123",
    "ts": "111.222",
}
_OVERHEARD: dict[str, Any] = {
    "type": "message",
    "channel_type": "channel",
    "channel": "C123",
    "ts": "111.222",
}


def _process_with_failure(
    req: MagicMock,
    fail_in: str = "_handle_request",
    respond_side_effect: Exception | None = None,
) -> MagicMock:
    """Fail inside `fail_in`, assert the error propagates, and return the reply mock."""
    failing = patch(f"{_LISTENER}.{fail_in}", side_effect=RuntimeError("lookup failed"))
    with (
        patch(f"{_LISTENER}.get_current_tenant_id", return_value="tenant_a"),
        patch(f"{_LISTENER}.prefilter_requests", return_value=True),
        patch(f"{_LISTENER}.build_request_details"),
        patch(f"{_LISTENER}._handle_request"),
        failing,
        patch(
            f"{_HANDLERS}.respond_in_thread_or_channel",
            side_effect=respond_side_effect,
        ) as mock_respond,
        pytest.raises(RuntimeError, match="lookup failed"),
    ):
        process_message(req, MagicMock())
    return mock_respond


@pytest.mark.parametrize("event", [_TAGGED, _DM], ids=["tagged", "dm"])
def test_addressed_sender_gets_the_generic_notice(event: dict[str, Any]) -> None:
    mock_respond = _process_with_failure(_event_request(event))

    mock_respond.assert_called_once()
    assert mock_respond.call_args.kwargs["text"] == SLACK_ANSWER_FAILED_MESSAGE
    assert mock_respond.call_args.kwargs["channel"] == event["channel"]
    assert mock_respond.call_args.kwargs["thread_ts"] == "111.222"


def test_notice_goes_to_the_thread_parent_for_a_message_inside_a_thread() -> None:
    mock_respond = _process_with_failure(
        _event_request({**_TAGGED, "ts": "333.444", "thread_ts": "111.222"})
    )

    assert mock_respond.call_args.kwargs["thread_ts"] == "111.222"


def test_overheard_message_gets_no_notice() -> None:
    """The bot reads every message in its channels. A failure on one that nobody
    sent to it must not post into that conversation."""
    mock_respond = _process_with_failure(_event_request(_OVERHEARD))

    mock_respond.assert_not_called()


def test_slash_command_notice_is_ephemeral_to_the_sender() -> None:
    mock_respond = _process_with_failure(_slash_request())

    mock_respond.assert_called_once()
    assert mock_respond.call_args.kwargs["receiver_ids"] == ["U123"]
    assert mock_respond.call_args.kwargs["thread_ts"] is None


def test_failure_before_the_request_details_exist_still_gets_a_notice() -> None:
    """Reading the thread needs a Slack scope that posting does not."""
    mock_respond = _process_with_failure(
        _event_request(_TAGGED), fail_in="build_request_details"
    )

    mock_respond.assert_called_once()


def test_the_original_error_survives_a_notice_that_cannot_be_sent() -> None:
    mock_respond = _process_with_failure(
        _event_request(_TAGGED),
        respond_side_effect=ConnectionError("slack unreachable"),
    )

    # The helper asserts that the original RuntimeError is what propagates.
    mock_respond.assert_called_once()


def _run_handle_request(handle_message: MagicMock) -> tuple[MagicMock, MagicMock]:
    """Run the real `_handle_request` and return the reminder-removal and reply mocks."""
    from onyx.onyxbot.slack.listener import _handle_request

    with (
        patch(f"{_LISTENER}.get_channel_name_from_id", return_value=("c", False)),
        patch(f"{_LISTENER}.get_session_with_current_tenant"),
        patch(f"{_LISTENER}.get_slack_channel_config_for_bot_and_channel"),
        patch(f"{_LISTENER}.schedule_feedback_reminder", return_value="reminder-1"),
        patch(f"{_LISTENER}.handle_message", handle_message),
        patch(f"{_LISTENER}.remove_scheduled_feedback_reminder") as mock_remove,
        patch(f"{_HANDLERS}.respond_in_thread_or_channel") as mock_respond,
    ):
        try:
            _handle_request(MagicMock(), MagicMock())
        except RuntimeError:
            pass
    return mock_remove, mock_respond


def test_ordinary_failed_answer_posts_nothing_from_the_listener() -> None:
    """The handler already told the user, so a message here would be a duplicate."""
    mock_remove, mock_respond = _run_handle_request(MagicMock(return_value=True))

    mock_remove.assert_called_once()
    mock_respond.assert_not_called()


def test_reminder_is_removed_when_handling_raises() -> None:
    """Otherwise the reminder asks for feedback on an answer that never came."""
    mock_remove, _ = _run_handle_request(MagicMock(side_effect=RuntimeError("db down")))

    mock_remove.assert_called_once()


def test_reminder_stays_after_a_delivered_answer() -> None:
    mock_remove, _ = _run_handle_request(MagicMock(return_value=False))

    mock_remove.assert_not_called()


@pytest.mark.parametrize(
    "error",
    [
        TimeoutError("slack down"),
        # A proxy's HTML 502 gives a Slack error whose response has no `error` key.
        SlackApiError("bad gateway", response={}),
        SlackApiError("gone", response={"error": "invalid_scheduled_message_id"}),
    ],
    ids=["timeout", "non-json-reply", "already-posted"],
)
def test_reminder_cleanup_cannot_raise(error: Exception) -> None:
    from onyx.onyxbot.slack.handlers.handle_message import (
        remove_scheduled_feedback_reminder,
    )

    client = MagicMock()
    client.chat_deleteScheduledMessage.side_effect = error

    remove_scheduled_feedback_reminder(client=client, channel="U123", msg_id="r-1")

    client.chat_deleteScheduledMessage.assert_called_once()


def test_unexpected_failure_clears_the_reaction() -> None:
    """A reaction that stays reads as still working."""
    with patch(f"{_LISTENER}.update_emote_react") as mock_react:
        _process_with_failure(_event_request(_TAGGED))

    mock_react.assert_called_once()
    assert mock_react.call_args.kwargs["remove"] is True
    assert mock_react.call_args.kwargs["message_ts"] == "111.222"
