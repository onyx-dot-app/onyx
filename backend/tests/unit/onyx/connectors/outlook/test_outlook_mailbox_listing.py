"""A mailbox listing groups rows by conversation in first-listed order, and a
read returns only the rows plan_documents keeps: the root and the newest
MAX_MESSAGES_PER_CONVERSATION messages, each message once, whether the read
trims a conversation at once or folds it in steps as it loads."""

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

import pytest

from onyx.connectors.cross_connector_utils import grouped_row_store
from onyx.connectors.cross_connector_utils.grouped_row_store import GroupedRowStore
from onyx.connectors.outlook.connector import _mailbox_listing
from onyx.connectors.outlook.models import OutlookMailbox, ThreadListing
from onyx.connectors.outlook.threads import (
    MAX_MESSAGES_PER_CONVERSATION,
    newest_rows,
    thread_root,
)


def _row(
    conversation_id: str,
    message_id: str,
    is_root: bool = False,
    received_at: datetime | None = datetime(2026, 1, 1, tzinfo=timezone.utc),
) -> ThreadListing:
    return ThreadListing(
        key=f"key-{conversation_id}",
        conversation_id=conversation_id,
        message_id=message_id,
        received_at=received_at,
        is_root=is_root,
        sender=OutlookMailbox(id="user-1", address="one@example.com"),
        named=[OutlookMailbox(id="user-2", address="two@example.com")],
    )


@pytest.fixture
def listing() -> Iterator[GroupedRowStore[ThreadListing]]:
    with _mailbox_listing() as listing:
        yield listing


def test_conversations_come_back_in_first_listed_order(
    listing: GroupedRowStore[ThreadListing],
) -> None:
    listing.add([_row("conv-b", "m1", is_root=True), _row("conv-a", "m2")])
    listing.add([_row("conv-b", "m3"), _row("conv-c", "m4")])

    listing.group()

    assert [[row.message_id for row in rows] for rows in listing.groups(0, 10)] == [
        ["m1", "m3"],
        ["m2"],
        ["m4"],
    ]


@pytest.mark.parametrize("fold_rows", [10_000, 7])
def test_a_read_keeps_the_root_and_the_newest_messages_once_each(
    listing: GroupedRowStore[ThreadListing],
    monkeypatch: pytest.MonkeyPatch,
    fold_rows: int,
) -> None:
    monkeypatch.setattr(grouped_row_store, "GROUP_FOLD_ROWS", fold_rows)
    first = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = [_row("conv", "root", is_root=True, received_at=first)] + [
        _row("conv", f"m{i}", received_at=first + timedelta(minutes=i))
        for i in range(1, MAX_MESSAGES_PER_CONVERSATION + 50)
    ]
    rows.append(_row("conv", "undated", received_at=None))
    # The same messages seen again from another folder, the root included.
    listing.add(rows)
    listing.add(rows[:1] + rows[-20:])
    listing.group()

    (kept,) = listing.groups(0, 1)

    assert [r.message_id for r in kept if r.is_root] == ["root"]
    assert newest_rows(kept, MAX_MESSAGES_PER_CONVERSATION) == newest_rows(
        rows, MAX_MESSAGES_PER_CONVERSATION
    )
    assert thread_root(kept) == thread_root(rows)
    assert "undated" not in {r.message_id for r in kept}
    assert len(kept) == MAX_MESSAGES_PER_CONVERSATION + 1
