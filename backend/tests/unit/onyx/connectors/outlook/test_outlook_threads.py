"""The thread key, the grouping of message copies into threads, the reader
rules, and the file store round trip of the attempt's thread table."""

import base64
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from onyx.connectors.outlook.models import OutlookMailbox, ThreadListing
from onyx.connectors.outlook.threads import (
    ThreadTable,
    candidate_copies,
    choose_builder,
    copy_document_id,
    delete_abandoned_tables,
    group_threads,
    newest_message_ids,
    partial_copies,
    readers_of,
    thread_document_id,
    thread_key,
)
from tests.unit.onyx.connectors.outlook.outlook_api_shapes import memory_file_store

ROOT = bytes(range(22))
ROOT_INDEX = base64.b64encode(ROOT).decode()
REPLY_INDEX = base64.b64encode(ROOT + bytes(5)).decode()
T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)


def _mailbox(n: int) -> OutlookMailbox:
    return OutlookMailbox(id=f"user-{n}", address=f"user{n}@contoso.com")


def _listing(key: str, mailbox_n: int, message: str, minute: int = 0) -> ThreadListing:
    return ThreadListing(
        key=key,
        mailbox=_mailbox(mailbox_n),
        conversation_id=f"conv-{key}-{mailbox_n}",
        message_id=message,
        received_at=T0 + timedelta(minutes=minute),
    )


def test_a_reply_shares_its_root_message_thread_key() -> None:
    assert thread_key(REPLY_INDEX) == thread_key(ROOT_INDEX)
    assert thread_key(ROOT_INDEX) is not None


def test_thread_key_is_safe_inside_a_document_id() -> None:
    key = thread_key(base64.b64encode(bytes([251, 255]) * 11).decode())
    assert key is not None
    assert "/" not in key and "+" not in key and "=" not in key
    assert thread_document_id(key) == f"outlook-thread:{key}"
    assert copy_document_id(key, _mailbox(1)) == f"outlook-thread:{key}:user-1"


def test_thread_key_rejects_short_or_malformed_indexes() -> None:
    assert thread_key(base64.b64encode(b"short").decode()) is None
    assert thread_key("not base64!") is None
    assert thread_key("") is None


def test_grouping_folds_copies_per_mailbox_and_finds_the_newest_message() -> None:
    groups = group_threads(
        [
            _listing("a", 1, "m1", 0),
            _listing("a", 2, "m1", 0),
            _listing("a", 1, "m2", 5),
            _listing("a", 1, "m2", 5),
            _listing("b", 2, "m9", 1),
        ]
    )

    by_key = {group.key: group for group in groups}
    assert set(by_key) == {"a", "b"}
    assert by_key["a"].newest_message_id == "m2"
    copies = {copy.mailbox.id: copy for copy in by_key["a"].copies}
    assert set(copies["user-1"].received) == {"m1", "m2"}
    assert set(copies["user-2"].received) == {"m1"}
    assert copies["user-1"].conversation_id == "conv-a-1"


def test_newest_message_ties_break_on_the_message_id_in_every_run() -> None:
    forward = group_threads([_listing("a", 1, "m-x", 0), _listing("a", 1, "m-y", 0)])
    backward = group_threads([_listing("a", 1, "m-y", 0), _listing("a", 1, "m-x", 0)])

    assert forward[0].newest_message_id == backward[0].newest_message_id == "m-y"


def test_readers_are_the_candidates_holding_every_message_of_the_builder() -> None:
    # Alice and Bob share the thread. Dave replied privately to Alice, and
    # Alice answered everyone: Alice holds all four, Bob three, Dave two.
    group = group_threads(
        [
            _listing("a", 1, "root", 0),
            _listing("a", 2, "root", 0),
            _listing("a", 3, "private", 1),
            _listing("a", 1, "private", 1),
            _listing("a", 1, "answer", 2),
            _listing("a", 2, "answer", 2),
        ]
    )[0]

    candidates = candidate_copies(group)
    assert {copy.mailbox.id for copy in candidates} == {"user-1", "user-2"}
    builder = choose_builder(candidates)
    assert builder.mailbox.id == "user-1"
    document_messages = newest_message_ids(builder, keep=100)
    assert document_messages == {"root", "private", "answer"}
    # Bob never received the private reply, so the thread document that
    # holds it is Alice's alone. Bob and Dave get documents of their own copies.
    readers = readers_of(candidates, document_messages)
    assert [m.id for m in readers] == ["user-1"]
    assert sorted(copy.mailbox.id for copy in partial_copies(group, readers)) == [
        "user-2",
        "user-3",
    ]


def test_builder_is_the_largest_copy_and_the_lowest_mailbox_id_on_a_tie() -> None:
    group = group_threads(
        [
            _listing("a", 2, "m1", 0),
            _listing("a", 2, "m2", 1),
            _listing("a", 1, "m2", 1),
            _listing("a", 3, "m1", 0),
            _listing("a", 3, "m2", 1),
        ]
    )[0]

    assert choose_builder(candidate_copies(group)).mailbox.id == "user-2"
    assert newest_message_ids(choose_builder(candidate_copies(group)), keep=1) == {"m2"}


def test_thread_table_round_trips_pages_into_buckets_and_cleans_up() -> None:
    store = memory_file_store()
    with (
        patch(
            "onyx.connectors.outlook.threads.get_default_file_store", return_value=store
        ),
        patch("onyx.connectors.outlook.threads.ROWS_PER_BUCKET", 2),
        patch("onyx.connectors.outlook.threads.BUCKET_FLUSH_ROWS", 1),
    ):
        table = ThreadTable("run")
        table.write_page(0, [_listing("a", 1, "m1"), _listing("b", 1, "m2")])
        table.write_page(1, [_listing("a", 2, "m1"), _listing("c", 2, "m3")])
        table.write_mailbox_exclusions("user-1", ["junk"])

        bucket_count = table.write_buckets(page_count=2, row_count=4)
        assert bucket_count == 2
        rows = [row for b in range(bucket_count) for row in table.read_bucket(b)]
        assert sorted((r.key, r.mailbox.id) for r in rows) == [
            ("a", "user-1"),
            ("a", "user-2"),
            ("b", "user-1"),
            ("c", "user-2"),
        ]
        # Every copy of a thread lands in the same bucket.
        for b in range(bucket_count):
            keys = {row.key for row in table.read_bucket(b)}
            assert sum(1 for r in rows if r.key in keys) == len(table.read_bucket(b))
        # Chunks and the manifest are plain JSON, so another run can read them.
        assert json.loads(store.files["outlook-threads/run/buckets.json"]) == [
            sum(
                1
                for f in store.files
                if f.startswith(f"outlook-threads/run/bucket-{b}-")
            )
            for b in range(bucket_count)
        ]
        assert ThreadTable("run").read_bucket(0) == table.read_bucket(0)

        assert table.read_mailbox_exclusions("user-1") == {"junk"}

        table.touch()
        table.delete_all()

    assert store.files == {}


def test_abandoned_tables_go_by_their_newest_write() -> None:
    now = datetime.now(timezone.utc)
    stale = now - timedelta(days=9)
    store = MagicMock()
    store.list_files_by_prefix.return_value = [
        MagicMock(file_id="outlook-threads/old/listing-0.json", created_at=stale),
        MagicMock(file_id="outlook-threads/old/touch.json", created_at=stale),
        MagicMock(file_id="outlook-threads/live/listing-0.json", created_at=stale),
        MagicMock(file_id="outlook-threads/live/touch.json", created_at=now),
    ]
    with patch(
        "onyx.connectors.outlook.threads.get_default_file_store", return_value=store
    ):
        delete_abandoned_tables(days_to_keep=7)

    deleted = {call.args[0] for call in store.delete_file.call_args_list}
    assert deleted == {
        "outlook-threads/old/listing-0.json",
        "outlook-threads/old/touch.json",
    }
