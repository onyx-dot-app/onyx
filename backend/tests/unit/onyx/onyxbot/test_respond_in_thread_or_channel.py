"""Tests that `respond_in_thread_or_channel` honors `send_as_ephemeral`.

Regression coverage for the bug where the ephemeral-vs-public decision was
driven solely by whether `receiver_ids` was non-empty. A channel allowlist
populates `receiver_ids`, so answers meant to be posted publicly
(`send_as_ephemeral=False`) were instead delivered as ephemeral messages and
were effectively invisible in the channel.
"""

from unittest.mock import MagicMock

from onyx.onyxbot.slack.utils import respond_in_thread_or_channel


def _client() -> MagicMock:
    client = MagicMock()
    client.chat_postMessage.return_value = {"message_ts": "111.000"}
    client.chat_postEphemeral.return_value = {"message_ts": "222.000"}
    return client


def test_no_receivers_posts_public_message() -> None:
    client = _client()
    respond_in_thread_or_channel(
        client=client, channel="C1", thread_ts=None, text="hi", receiver_ids=None
    )
    client.chat_postMessage.assert_called_once()
    client.chat_postEphemeral.assert_not_called()


def test_ephemeral_false_posts_public_even_with_receivers() -> None:
    client = _client()
    respond_in_thread_or_channel(
        client=client,
        channel="C1",
        thread_ts=None,
        text="hi",
        receiver_ids=["U1", "U2"],
        send_as_ephemeral=False,
    )
    # The regression: with receivers set this used to force ephemeral delivery.
    client.chat_postMessage.assert_called_once()
    client.chat_postEphemeral.assert_not_called()


def test_ephemeral_true_posts_to_each_receiver() -> None:
    client = _client()
    respond_in_thread_or_channel(
        client=client,
        channel="C1",
        thread_ts=None,
        text="hi",
        receiver_ids=["U1", "U2"],
        send_as_ephemeral=True,
    )
    assert client.chat_postEphemeral.call_count == 2
    client.chat_postMessage.assert_not_called()


def test_default_with_receivers_stays_ephemeral() -> None:
    # Preserve prior default behavior: when send_as_ephemeral is not passed
    # (defaults to True) and receivers are set, delivery stays ephemeral.
    client = _client()
    respond_in_thread_or_channel(
        client=client,
        channel="C1",
        thread_ts=None,
        text="hi",
        receiver_ids=["U1"],
    )
    client.chat_postEphemeral.assert_called_once()
    client.chat_postMessage.assert_not_called()
