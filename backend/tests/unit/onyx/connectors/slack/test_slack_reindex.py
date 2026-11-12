"""Targeted reindex of a thread whose root the message filter drops: the crawl
ids the doc by its first kept reply, and reindex must read the whole thread
from that reply id."""

from typing import Any, cast
from unittest.mock import MagicMock

from onyx.connectors.models import ConnectorFailure, Document, DocumentFailure
from onyx.connectors.slack.connector import SlackConnector, _message_to_doc
from onyx.connectors.slack.models import ChannelType, MessageType
from onyx.connectors.slack.source_operations import (
    SlackAuthTestResponse,
    SlackChannelInfoResponse,
    SlackHistoryPage,
    SlackSourceOperations,
)
from onyx.connectors.slack.utils import SlackTextCleaner

_CHANNEL: dict[str, Any] = {
    "id": "C0123456789",
    "name": "general",
    "is_member": True,
    "is_private": False,
    "is_archived": False,
    "is_im": False,
    "is_mpim": False,
}
_ROOT_TS = "1700000000.000100"
_BOT_ROOT: dict[str, Any] = {
    "ts": _ROOT_TS,
    "thread_ts": _ROOT_TS,
    "text": "Deploy finished",
    "bot_id": "B1",
}
_REPLIES: list[dict[str, Any]] = [
    {"ts": "1700000001.000100", "thread_ts": _ROOT_TS, "text": "first", "user": "U1"},
    {"ts": "1700000002.000100", "thread_ts": _ROOT_TS, "text": "second", "user": "U2"},
    {"ts": "1700000003.000100", "thread_ts": _ROOT_TS, "text": "third", "user": "U1"},
]
_REPLY_DOC_ID = f"{_CHANNEL['id']}__{_REPLIES[0]['ts']}"


def _fetch_thread_replies(**kwargs: Any) -> Any:
    # Slack returns the whole thread for its root ts, and only the reply for
    # a reply ts.
    thread_ts = kwargs["thread_ts"]
    if thread_ts == _ROOT_TS:
        messages = [_BOT_ROOT, *_REPLIES]
    else:
        messages = [m for m in _REPLIES if m["ts"] == thread_ts]
    return iter([SlackHistoryPage(ok=True, messages=messages)])


def _client() -> MagicMock:
    client = MagicMock(spec=SlackSourceOperations)
    client.check_auth.return_value = SlackAuthTestResponse(
        ok=True, url="https://test.slack.com/"
    )
    client.fetch_channel_info.return_value = SlackChannelInfoResponse(channel=_CHANNEL)
    client.fetch_thread_replies.side_effect = _fetch_thread_replies
    return client


def _connector(client: MagicMock) -> SlackConnector:
    connector = SlackConnector(include_bot_messages=False, use_redis=False)
    connector.slack_client = client
    connector.text_cleaner = SlackTextCleaner(fetch_user_info=client.fetch_user_info)
    connector.user_cache = {"U1": None, "U2": None}
    return connector


def test_reindex_reads_whole_thread_for_reply_based_id() -> None:
    client = _client()
    connector = _connector(client)

    crawled, _ = _message_to_doc(
        message=cast(MessageType, _BOT_ROOT),
        slack_client=client,
        channel=cast(ChannelType, _CHANNEL),
        slack_cleaner=SlackTextCleaner(fetch_user_info=client.fetch_user_info),
        user_cache=connector.user_cache,
        seen_thread_ts=set(),
        channel_access=None,
    )
    assert crawled is not None
    assert crawled.id == _REPLY_DOC_ID

    results = list(
        connector.reindex(
            [
                ConnectorFailure(
                    failed_document=DocumentFailure(document_id=_REPLY_DOC_ID),
                    failure_message="synthetic",
                )
            ]
        )
    )

    docs = [r for r in results if isinstance(r, Document)]
    assert [r for r in results if isinstance(r, ConnectorFailure)] == []
    assert len(docs) == 1
    assert docs[0].id == _REPLY_DOC_ID
    assert [s.text for s in docs[0].sections] == ["first", "second", "third"]
    assert [s.text for s in docs[0].sections] == [s.text for s in crawled.sections]
    assert [
        call.kwargs["thread_ts"] for call in client.fetch_thread_replies.call_args_list
    ][-2:] == [_REPLIES[0]["ts"], _ROOT_TS]
