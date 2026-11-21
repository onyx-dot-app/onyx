"""Backfilling a channel with more messages than one history page.

Slack returns the newest ``limit`` messages in ``[oldest, latest)`` first. The
checkpoint must therefore walk a channel backwards: resume with ``latest`` set
to the oldest message already seen and keep ``oldest`` pinned to the start of
the range. Resuming with ``oldest`` set to the newest message seen requests an
empty range and silently drops everything older than the first page.
"""

from typing import Any
from unittest.mock import MagicMock

import pytest

from onyx.connectors.models import Document
from onyx.connectors.slack import connector as slack_connector
from onyx.connectors.slack.connector import SlackCheckpoint, SlackConnector
from onyx.connectors.slack.models import ChannelType
from onyx.connectors.slack.source_operations import (
    SlackAuthTestResponse,
    SlackHistoryPage,
    SlackResponseMetadata,
    SlackSourceOperations,
)
from onyx.connectors.slack.utils import SlackTextCleaner
from tests.unit.onyx.connectors.utils import (
    load_everything_from_checkpoint_connector_from_checkpoint,
)

_PAGE_LIMIT = 10
_CHANNEL: ChannelType = {
    "id": "C0123456789",
    "name": "alerts",
    "name_normalized": "alerts",
    "is_channel": True,
    "is_group": False,
    "is_im": False,
    "is_mpim": False,
    "created": 1_600_000_000,
    "creator": "U1",
    "is_archived": False,
    "is_general": False,
    "unlinked": 0,
    "is_shared": False,
    "is_ext_shared": False,
    "is_org_shared": False,
    "pending_shared": [],
    "is_pending_ext_shared": False,
    "is_member": True,
    "is_private": False,
    "updated": 1_600_000_000,
    "topic": {"value": "", "creator": "", "last_set": 0},
    "purpose": {"value": "", "creator": "", "last_set": 0},
    "previous_names": [],
    "num_members": 1,
}
_START = 1_700_000_000
_END = _START + 1_000


def _ts(i: int) -> str:
    return f"{_START + i}.000100"


def _history_client(num_messages: int) -> MagicMock:
    """A fake ``conversations.history`` with Slack's paging semantics: newest
    first, ``oldest``/``latest`` exclusive, at most ``limit`` per page."""
    all_messages = [
        {"ts": _ts(i), "text": f"message {i}", "user": "U1"}
        for i in range(1, num_messages + 1)
    ]

    def fetch_channel_history(**kwargs: Any) -> Any:
        oldest = float(kwargs["oldest"]) if kwargs["oldest"] else float("-inf")
        latest = float(kwargs["latest"]) if kwargs["latest"] else float("inf")
        in_range = [m for m in all_messages if oldest < float(m["ts"]) < latest]
        in_range.sort(key=lambda m: float(m["ts"]), reverse=True)
        limit = kwargs["limit"]
        page, rest = in_range[:limit], in_range[limit:]
        return iter(
            [
                SlackHistoryPage(
                    ok=True,
                    messages=page,
                    response_metadata=SlackResponseMetadata(
                        next_cursor="more" if rest else ""
                    ),
                )
            ]
        )

    client = MagicMock(spec=SlackSourceOperations)
    client.check_auth.return_value = SlackAuthTestResponse(
        ok=True, url="https://test.slack.com/"
    )
    client.fetch_channel_history.side_effect = fetch_channel_history
    return client


def _connector(client: MagicMock) -> SlackConnector:
    connector = SlackConnector(include_bot_messages=True, use_redis=False)
    connector.slack_client = client
    connector.text_cleaner = SlackTextCleaner(fetch_user_info=client.fetch_user_info)
    connector.user_cache = {"U1": None}
    return connector


@pytest.fixture(autouse=True)
def _small_history_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    """Shrink the page size so a handful of messages spans several pages."""
    real_get_messages = slack_connector._get_messages
    monkeypatch.setattr(
        slack_connector,
        "_get_messages",
        lambda channel, client, oldest, latest: real_get_messages(
            channel, client, oldest, latest, limit=_PAGE_LIMIT
        ),
    )


def _checkpoint() -> SlackCheckpoint:
    # Skip channel discovery: start directly on the one channel under test.
    return SlackCheckpoint(
        channel_ids=[_CHANNEL["id"]],
        channel_completion_map={},
        current_channel=_CHANNEL,
        current_channel_access=None,
        seen_thread_ts=[],
        has_more=True,
    )


@pytest.mark.parametrize("num_messages", [3, _PAGE_LIMIT, _PAGE_LIMIT + 1, 95])
def test_backfill_indexes_every_message_beyond_one_page(num_messages: int) -> None:
    client = _history_client(num_messages)
    connector = _connector(client)

    outputs = load_everything_from_checkpoint_connector_from_checkpoint(
        connector, 0, _END, _checkpoint()
    )

    docs = [
        item
        for output in outputs
        for item in output.items
        if isinstance(item, Document)
    ]
    assert len(docs) == num_messages
    assert len({d.id for d in docs}) == num_messages
    assert {d.id for d in docs} == {
        f"{_CHANNEL['id']}__{_ts(i)}" for i in range(1, num_messages + 1)
    }


def test_backfill_walks_backwards_and_keeps_range_start_pinned() -> None:
    client = _history_client(25)
    connector = _connector(client)

    load_everything_from_checkpoint_connector_from_checkpoint(
        connector, _START, _END, _checkpoint()
    )

    calls = client.fetch_channel_history.call_args_list
    # 25 messages at 10 per page: three pages, then the channel is done
    assert len(calls) == 3
    assert all(c.kwargs["oldest"] == str(_START) for c in calls)
    # each page resumes strictly before the oldest message of the previous one
    assert calls[0].kwargs["latest"] == str(_END)
    assert calls[1].kwargs["latest"] == _ts(16)
    assert calls[2].kwargs["latest"] == _ts(6)
