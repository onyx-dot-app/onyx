"""The thread key, the merge of listings into build entries, and the file
store round trip of the attempt's thread table."""

import base64
import json
from unittest.mock import patch

from onyx.connectors.outlook.models import OutlookMailbox
from onyx.connectors.outlook.threads import (
    ThreadListing,
    ThreadTable,
    merge_listings,
    thread_document_id,
    thread_key,
)
from tests.unit.onyx.connectors.outlook.outlook_api_shapes import memory_file_store

ROOT = bytes(range(22))
ROOT_INDEX = base64.b64encode(ROOT).decode()
REPLY_INDEX = base64.b64encode(ROOT + bytes(5)).decode()


def _mailbox(n: int) -> OutlookMailbox:
    return OutlookMailbox(id=f"user-{n}", address=f"user{n}@contoso.com")


def _listing(key: str, mailbox_n: int, conversation_id: str = "conv") -> ThreadListing:
    return ThreadListing(
        key=key,
        mailbox=_mailbox(mailbox_n),
        conversation_id=conversation_id,
    )


def test_a_reply_shares_its_root_message_thread_key() -> None:
    assert thread_key(REPLY_INDEX) == thread_key(ROOT_INDEX)
    assert thread_key(ROOT_INDEX) is not None


def test_thread_key_is_safe_inside_a_document_id() -> None:
    key = thread_key(base64.b64encode(bytes([251, 255]) * 11).decode())
    assert key is not None
    assert "/" not in key and "+" not in key and "=" not in key
    assert thread_document_id(key) == f"outlook-thread:{key}"


def test_thread_key_rejects_short_or_malformed_indexes() -> None:
    assert thread_key(base64.b64encode(b"short").decode()) is None
    assert thread_key("not base64!") is None
    assert thread_key("") is None


def test_merge_keeps_the_first_listing_and_every_holder_once() -> None:
    entries = merge_listings(
        [
            _listing("a", 1, "conv-a1"),
            _listing("b", 1, "conv-b1"),
            _listing("a", 2, "conv-a2"),
            _listing("a", 1, "conv-a1-again"),
        ]
    )

    by_key = {entry.key: entry for entry in entries}
    assert list(by_key) == ["a", "b"]
    assert by_key["a"].first.conversation_id == "conv-a1"
    assert [h.id for h in by_key["a"].holders] == ["user-1", "user-2"]
    assert [h.id for h in by_key["b"].holders] == ["user-1"]


def test_thread_table_round_trips_pages_into_shards_and_cleans_up() -> None:
    store = memory_file_store()
    with patch(
        "onyx.connectors.outlook.threads.get_default_file_store", return_value=store
    ):
        table = ThreadTable("run")
        table.write_page(0, [_listing("a", 1), _listing("b", 1)])
        table.write_page(1, [_listing("a", 2), _listing("c", 2)])
        table.write_mailbox_exclusions("user-1", ["junk"])

        entries = merge_listings(table.iter_pages(2))
        shards = table.write_shards(entries, per_shard=2)
        assert shards == 2
        assert [e.key for e in table.read_shard(0)] == ["a", "b"]
        assert [e.key for e in table.read_shard(1)] == ["c"]
        assert [h.id for h in table.read_shard(0)[0].holders] == ["user-1", "user-2"]
        # Pages and shards are plain JSON, so another run can read them.
        assert (
            json.loads(store.files["outlook-threads/run/shard-1.json"])[0]["key"] == "c"
        )

        assert table.read_mailbox_exclusions("user-1") == {"junk"}

        table.delete_all()

    assert store.files == {}
