"""The Slack targeted reindex reads each failed thread again by the channel id
and root timestamp its document id is built from, and keys every outcome on
that same id."""

from typing import Any, cast
from unittest.mock import MagicMock, create_autospec

import pytest

from onyx.connectors.models import (
    ConnectorFailure,
    Document,
    DocumentFailure,
    HierarchyNode,
)
from onyx.connectors.slack.connector import SlackConnector
from onyx.connectors.slack.models import ChannelType, MessageType
from onyx.connectors.slack.source_operations import (
    SlackAuthTestResponse,
    SlackChannelInfoResponse,
    SlackHistoryPage,
    SlackSourceOperations,
    SlackUserInfoResponse,
)
from onyx.connectors.slack.utils import SlackTextCleaner


def _channel(channel_id: str, **overrides: Any) -> ChannelType:
    base: dict[str, Any] = {
        "id": channel_id,
        "name": f"chan-{channel_id.lower()}",
        "is_channel": True,
        "is_group": False,
        "is_im": False,
        "created": 0,
        "creator": "U1",
        "is_archived": False,
        "is_general": False,
        "unlinked": 0,
        "name_normalized": f"chan-{channel_id.lower()}",
        "is_shared": False,
        "is_ext_shared": False,
        "is_org_shared": False,
        "pending_shared": [],
        "is_pending_ext_shared": False,
        "is_member": True,
        "is_private": False,
        "is_mpim": False,
        "updated": 0,
        "topic": {"value": "", "creator": "", "last_set": 0},
        "purpose": {"value": "", "creator": "", "last_set": 0},
        "previous_names": [],
        "num_members": 0,
    }
    base.update(overrides)
    return cast(ChannelType, base)


def _msg(ts: str, thread_ts: str | None = None, **overrides: Any) -> MessageType:
    data: dict[str, Any] = {"type": "message", "user": "U1", "text": "hi", "ts": ts}
    if thread_ts is not None:
        data["thread_ts"] = thread_ts
    data.update(overrides)
    return cast(MessageType, data)


def _failure(document_id: str) -> ConnectorFailure:
    return ConnectorFailure(
        failed_document=DocumentFailure(document_id=document_id, document_link=None),
        failure_message="synthetic",
    )


@pytest.fixture
def gateway() -> MagicMock:
    client: MagicMock = create_autospec(SlackSourceOperations, instance=True)
    client.check_auth.return_value = SlackAuthTestResponse(
        ok=True, url="https://acme.slack.com/"
    )
    client.fetch_user_info.return_value = SlackUserInfoResponse(
        ok=True, user={"real_name": "Ada", "profile": {}}
    )
    client.fetch_channel_info.side_effect = lambda *, channel_id: (
        SlackChannelInfoResponse(channel=_channel(channel_id))
    )
    # "1.0" has a reply, "2.0" is a lone message, "3.0" is bot-posted, "4.0" has
    # a bot reply under a human root, "5.0" a human reply under a bot root,
    # anything else is gone.
    threads = {
        "1.0": [_msg("1.0", "1.0"), _msg("1.5", "1.0")],
        "2.0": [_msg("2.0")],
        "3.0": [_msg("3.0", bot_id="B1")],
        "4.0": [_msg("4.0", "4.0"), _msg("4.5", "4.0", bot_id="B1")],
        "5.0": [_msg("5.0", "5.0", bot_id="B1"), _msg("5.5", "5.0")],
    }
    client.fetch_thread_replies.side_effect = lambda *, thread_ts, **_kwargs: iter(
        [SlackHistoryPage(ok=True, messages=threads.get(thread_ts, []))]
    )
    return client


@pytest.fixture
def connector(gateway: MagicMock) -> SlackConnector:
    connector = SlackConnector(use_redis=False)
    connector.slack_client = gateway
    connector.text_cleaner = SlackTextCleaner(fetch_user_info=gateway.fetch_user_info)
    return connector


def test_reindex_reads_threads_by_channel_and_root_timestamp(
    connector: SlackConnector, gateway: MagicMock
) -> None:
    outputs = list(
        connector.reindex(
            [
                _failure("C1__1.0"),
                _failure("C1__2.0"),
                _failure("C1__4.0"),
                _failure("C1__5.0"),
            ]
        )
    )

    nodes = [o for o in outputs if isinstance(o, HierarchyNode)]
    documents = [o for o in outputs if isinstance(o, Document)]
    assert [n.raw_node_id for n in nodes] == ["C1"]
    assert [d.id for d in documents] == ["C1__1.0", "C1__2.0", "C1__4.0", "C1__5.0"]
    assert len(documents[0].sections) == 2
    # Bot messages are dropped, as the crawl drops them. A dropped root still
    # names the thread, so the retry clears the failure the crawl recorded.
    assert len(documents[2].sections) == 1
    assert len(documents[3].sections) == 1
    assert documents[0].sections[0].link == (
        "https://acme.slack.com/archives/C1/p10?thread_ts=1.0"
    )
    gateway.fetch_channel_info.assert_called_once_with(channel_id="C1")
    assert not any(isinstance(o, ConnectorFailure) for o in outputs)


def test_reindex_keys_every_failure_on_the_target_id(
    connector: SlackConnector,
) -> None:
    outputs = list(
        connector.reindex([_failure("C1__9.0"), _failure("C1__3.0"), _failure("nope")])
    )

    failures = [o for o in outputs if isinstance(o, ConnectorFailure)]
    assert [f.failed_document.document_id for f in failures if f.failed_document] == [
        "C1__9.0",
        "C1__3.0",
        "nope",
    ]
    assert "no longer returns" in failures[0].failure_message
    assert "bot" in failures[1].failure_message
    assert "Not a Slack document id" in failures[2].failure_message
    assert not any(isinstance(o, Document) for o in outputs)
