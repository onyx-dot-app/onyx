"""The on-disk mailbox listing: rows round-trip through sqlite, conversations
come back in first-listed order with their rows in listing order, a read
returns only the rows plan_documents keeps, reads are sliced, and closing
releases the file. A listing of 300k rows across 100k conversations reads
back whole in slices."""

import sqlite3
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

import pytest

from onyx.connectors.outlook import connector as connector_module
from onyx.connectors.outlook.connector import _MailboxListing
from onyx.connectors.outlook.models import OutlookMailbox, ThreadListing
from onyx.connectors.outlook.threads import (
    MAX_MESSAGES_PER_CONVERSATION,
    newest_rows,
    thread_root,
)

LARGE_LISTING_ROWS = 300_000
LARGE_LISTING_CONVERSATIONS = 100_000


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
def listing() -> Iterator[_MailboxListing]:
    listing = _MailboxListing()
    yield listing
    listing.close()


def test_conversations_come_back_in_first_listed_order_with_rows_intact(
    listing: _MailboxListing,
) -> None:
    listing.add([_row("conv-b", "m1", is_root=True), _row("conv-a", "m2")])
    listing.add([_row("conv-b", "m3"), _row("conv-c", "m4")])

    listing.group()

    assert listing.conversation_count == 3
    conversations = listing.conversations(0, 10)
    assert [[row.message_id for row in rows] for rows in conversations] == [
        ["m1", "m3"],
        ["m2"],
        ["m4"],
    ]
    assert conversations[0][0] == _row("conv-b", "m1", is_root=True)


def test_reads_are_sliced_and_cover_every_conversation_once(
    listing: _MailboxListing, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(connector_module, "LISTING_READ_SIZE", 3)
    listing.add([_row(f"conv-{i}", f"m{i}") for i in range(7)])
    listing.group()

    slices = [listing.conversations(start, 3) for start in (0, 3, 6, 9)]

    assert [len(s) for s in slices] == [3, 3, 1, 0]
    assert [rows[0].conversation_id for s in slices for rows in s] == [
        f"conv-{i}" for i in range(7)
    ]
    assert [rows[0].conversation_id for rows in listing.all_conversations()] == [
        f"conv-{i}" for i in range(7)
    ]


def test_a_read_keeps_the_root_and_the_newest_messages_once_each(
    listing: _MailboxListing,
) -> None:
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

    (kept,) = listing.conversations(0, 1)

    assert [r.message_id for r in kept if r.is_root] == ["root"]
    assert newest_rows(kept, MAX_MESSAGES_PER_CONVERSATION) == newest_rows(
        rows, MAX_MESSAGES_PER_CONVERSATION
    )
    assert thread_root(kept) == thread_root(rows)
    assert "undated" not in {r.message_id for r in kept}
    assert len(kept) == MAX_MESSAGES_PER_CONVERSATION + 1


def test_close_releases_the_database() -> None:
    listing = _MailboxListing()

    listing.close()

    with pytest.raises(sqlite3.ProgrammingError):
        listing.conversations(0, 1)


def test_a_listing_the_size_of_a_large_mailbox_reads_back_in_slices(
    listing: _MailboxListing,
) -> None:
    listing.add(
        _row(f"conv-{i % LARGE_LISTING_CONVERSATIONS}", f"m{i}")
        for i in range(LARGE_LISTING_ROWS)
    )
    listing.group()

    assert listing.conversation_count == LARGE_LISTING_CONVERSATIONS
    rows_per_conversation = LARGE_LISTING_ROWS // LARGE_LISTING_CONVERSATIONS
    seen = 0
    for rows in listing.all_conversations():
        assert len(rows) == rows_per_conversation
        seen += 1
    assert seen == LARGE_LISTING_CONVERSATIONS
