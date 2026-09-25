"""Checkpoint pagination over a channel whose history spans several pages.

Slack returns ``conversations.history`` newest first, and ``oldest`` /
``latest`` are exclusive bounds. The fake gateway below models exactly that,
so the connector must walk backwards page by page until the channel is
exhausted.
"""

from typing import Any
from unittest.mock import MagicMock, create_autospec

from onyx.connectors.models import Document
from onyx.connectors.slack.connector import SlackConnector, _WorkspaceMetadata
from onyx.connectors.slack.source_operations import (
    SlackAuthTestResponse,
    SlackChannelsPage,
    SlackHistoryPage,
    SlackResponseMetadata,
    SlackSourceOperations,
    SlackUserInfoResponse,
)
from onyx.connectors.slack.utils import SlackTextCleaner
from tests.unit.onyx.connectors.utils import load_everything_from_checkpoint_connector

_CHANNEL: dict[str, Any] = {
    "id": "C1",
    "name": "general",
    "is_member": True,
    "is_private": False,
    "created": 900,
}

# Smaller than the connector's request limit; Slack may return fewer messages
# than ``limit`` and signal more with a cursor, so the fake does the same.
_PAGE_SIZE = 2


def _message(ts: str) -> dict[str, Any]:
    return {"ts": ts, "user": "U1", "text": f"message {ts}", "type": "message"}


def _history_fake(all_messages: list[dict[str, Any]]) -> Any:
    """``fetch_channel_history`` over a fixed channel history.

    Applies the exclusive ``oldest`` / ``latest`` bounds, returns newest first,
    and sets ``next_cursor`` while older messages remain in range.
    """
    newest_first = sorted(all_messages, key=lambda m: float(m["ts"]), reverse=True)

    def fetch(
        *,
        variant: Any,
        channel_id: str,
        oldest: str | None = None,
        latest: str | None = None,
        limit: int | None = None,
    ) -> Any:
        del variant, channel_id, limit
        in_range = [
            m
            for m in newest_first
            if (oldest is None or float(m["ts"]) > float(oldest))
            and (latest is None or float(m["ts"]) < float(latest))
        ]
        page = in_range[:_PAGE_SIZE]
        has_more = len(in_range) > _PAGE_SIZE
        yield SlackHistoryPage(
            ok=True,
            messages=page,
            response_metadata=SlackResponseMetadata(
                next_cursor="next" if has_more else ""
            ),
        )

    return fetch


def _channels_fake(**kwargs: Any) -> Any:
    del kwargs
    return iter([SlackChannelsPage(ok=True, channels=[_CHANNEL])])


def _connector(all_messages: list[dict[str, Any]]) -> tuple[SlackConnector, MagicMock]:
    gateway = create_autospec(SlackSourceOperations, instance=True)
    gateway.check_auth.return_value = SlackAuthTestResponse(
        ok=True, url="https://example.slack.com"
    )
    gateway.list_channels.side_effect = _channels_fake
    gateway.fetch_channel_history.side_effect = _history_fake(all_messages)
    gateway.fetch_user_info.return_value = SlackUserInfoResponse(
        ok=True, user={"real_name": "Test User", "profile": {}}
    )

    connector = SlackConnector(channels=None, use_redis=False, num_threads=1)
    connector.slack_client = gateway
    connector.text_cleaner = SlackTextCleaner(fetch_user_info=gateway.fetch_user_info)
    connector._workspace_metadata = _WorkspaceMetadata(url="https://example.slack.com")
    return connector, gateway


def test_checkpoint_resume_walks_every_history_page() -> None:
    all_messages = [_message(f"{1000 + i}.000100") for i in range(5)]
    connector, gateway = _connector(all_messages)

    outputs = load_everything_from_checkpoint_connector(
        connector, start=0.0, end=2000.0
    )

    doc_ids = [
        item.id
        for output in outputs
        for item in output.items
        if isinstance(item, Document)
    ]
    expected_ids = [f"C1__{m['ts']}" for m in all_messages]

    assert sorted(doc_ids) == sorted(expected_ids)
    assert len(doc_ids) == len(set(doc_ids))

    # Each page resumes strictly below the oldest message already processed.
    latest_bounds = [
        call.kwargs["latest"] for call in gateway.fetch_channel_history.call_args_list
    ]
    assert latest_bounds == ["2000.0", "1003.000100", "1001.000100"]
    assert all(
        call.kwargs["oldest"] is None
        for call in gateway.fetch_channel_history.call_args_list
    )


def test_checkpoint_resume_within_finite_poll_window() -> None:
    # Messages span below the window start; only those strictly newer than
    # ``start`` belong to this poll, and they still span several pages.
    all_messages = [_message(f"{1000 + i}.000100") for i in range(8)]
    connector, gateway = _connector(all_messages)

    outputs = load_everything_from_checkpoint_connector(
        connector, start=1002.5, end=2000.0
    )

    doc_ids = [
        item.id
        for output in outputs
        for item in output.items
        if isinstance(item, Document)
    ]
    expected_ids = [f"C1__{m['ts']}" for m in all_messages if float(m["ts"]) > 1002.5]

    assert sorted(doc_ids) == sorted(expected_ids)
    assert len(doc_ids) == len(set(doc_ids))

    calls = gateway.fetch_channel_history.call_args_list
    # Every request keeps the window's lower bound ...
    assert [call.kwargs["oldest"] for call in calls] == ["1002.5"] * 3
    # ... while ``latest`` walks down below the oldest message already processed.
    assert [call.kwargs["latest"] for call in calls] == [
        "2000.0",
        "1006.000100",
        "1004.000100",
    ]
