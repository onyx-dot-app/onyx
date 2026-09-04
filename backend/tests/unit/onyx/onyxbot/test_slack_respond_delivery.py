"""Tests for how `respond_in_thread_or_channel` picks a delivery mode."""

from unittest.mock import MagicMock

import pytest

from onyx.onyxbot.slack.utils import respond_in_thread_or_channel


def _make_client() -> MagicMock:
    client = MagicMock()
    client.chat_postMessage.return_value = {"message_ts": "1700000000.000100"}
    client.chat_postEphemeral.return_value = {"message_ts": "1700000000.000200"}
    return client


def test_no_receivers_posts_publicly() -> None:
    client = _make_client()

    respond_in_thread_or_channel(
        client=client,
        channel="C123",
        thread_ts=None,
        text="hello",
        receiver_ids=None,
    )

    client.chat_postMessage.assert_called_once()
    client.chat_postEphemeral.assert_not_called()


def test_receivers_with_ephemeral_consent_posts_ephemerally() -> None:
    client = _make_client()

    message_ids = respond_in_thread_or_channel(
        client=client,
        channel="C123",
        thread_ts=None,
        text="hello",
        receiver_ids=["U1", "U2"],
        send_as_ephemeral=True,
    )

    assert client.chat_postEphemeral.call_count == 2
    client.chat_postMessage.assert_not_called()
    assert len(message_ids) == 2


def test_omitting_send_as_ephemeral_keeps_receiver_driven_delivery() -> None:
    """Callers that don't pass the flag keep the historical behavior."""
    client = _make_client()

    respond_in_thread_or_channel(
        client=client,
        channel="C123",
        thread_ts=None,
        text="hello",
        receiver_ids=["U1"],
    )

    client.chat_postEphemeral.assert_called_once()
    client.chat_postMessage.assert_not_called()


@pytest.mark.parametrize("send_as_ephemeral", [False, None], ids=["false", "none"])
def test_receivers_without_ephemeral_consent_posts_publicly(
    send_as_ephemeral: bool | None,
) -> None:
    """A caller asking for a public post gets one even when receivers are set.

    `receiver_ids` alone used to force ephemeral delivery, so a caller that
    explicitly passed `send_as_ephemeral=False` was silently overridden. That
    made the bot-DM carve-out in `handle_regular_answer` dead code, because it
    sets the flag to False and still forwards the channel allowlist as
    `receiver_ids`.
    """
    client = _make_client()

    respond_in_thread_or_channel(
        client=client,
        channel="C123",
        thread_ts="1700000000.000001",
        text="hello",
        receiver_ids=["U1", "U2"],
        send_as_ephemeral=send_as_ephemeral,
    )

    client.chat_postMessage.assert_called_once()
    client.chat_postEphemeral.assert_not_called()
