"""Indexing skips a channel Slack refuses to let the bot join, and only such
channels: errors about the run propagate, and the slim listing used by
pruning never skips, so a refused channel cannot read as deleted history."""

from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from slack_sdk.errors import SlackApiError

from onyx.connectors.slack.connector import _get_messages, get_channel_messages
from onyx.connectors.slack.models import ChannelType
from onyx.connectors.slack.source_operations import (
    SlackHistoryPage,
    SlackSourceOperations,
)


def _channel(is_member: bool) -> ChannelType:
    base: dict[str, Any] = {
        "id": "C123",
        "name": "restricted",
        "is_member": is_member,
        "is_private": False,
    }
    return cast(ChannelType, base)


def _client(join_error: str | None) -> MagicMock:
    client = MagicMock(spec=SlackSourceOperations)
    if join_error is not None:
        client.join_channel.side_effect = SlackApiError(
            "slack api error", {"ok": False, "error": join_error}
        )
    client.fetch_channel_history.return_value = iter(
        [SlackHistoryPage(ok=True, messages=[{"ts": "1.0", "text": "hi"}])]
    )
    return client


@pytest.mark.parametrize("join_error", ["is_archived", "restricted_action"])
def test_indexing_skips_channel_when_join_is_refused(join_error: str) -> None:
    client = _client(join_error)

    assert _get_messages(_channel(is_member=False), client) == ([], False)
    client.fetch_channel_history.assert_not_called()


@pytest.mark.parametrize(
    "join_error", ["invalid_auth", "missing_scope", "internal_error"]
)
def test_indexing_propagates_errors_about_the_run(join_error: str) -> None:
    client = _client(join_error)

    with pytest.raises(SlackApiError):
        _get_messages(_channel(is_member=False), client)


def test_slim_listing_propagates_a_refused_join() -> None:
    client = _client("restricted_action")

    with pytest.raises(SlackApiError):
        list(get_channel_messages(client, _channel(is_member=False)))
    client.fetch_channel_history.assert_not_called()


def test_indexing_reads_history_after_joining() -> None:
    client = _client(None)

    messages, has_more = _get_messages(_channel(is_member=False), client)

    client.join_channel.assert_called_once_with(channel_id="C123")
    assert [message["text"] for message in messages] == ["hi"]
    assert has_more is False


def test_no_join_when_already_a_member() -> None:
    client = _client(None)

    _get_messages(_channel(is_member=True), client)

    client.join_channel.assert_not_called()
