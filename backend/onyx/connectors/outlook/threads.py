"""One document per mail thread, however many mailboxes hold a copy.

A thread is keyed by the root of its conversation index, which Outlook sets
on the first message and copies into every reply in every mailbox. The
conversation id differs per mailbox, so it cannot serve. Messages are matched
across mailboxes by Internet Message-ID. The document is built from the copy
holding the newest message and the most messages, readable by the mailboxes
that hold every message in it, and every other copy gets a document of its
own. Indexing and the slim walk apply the same rules. The listing lives in
the file store under the attempt's run id: one page per listing step, then
the listing re-cut into buckets by thread key, plus one file per finished
mailbox with its excluded folder ids.
"""

import base64
import binascii
import json
import math
import zlib
from collections.abc import Generator, Iterable, Sequence
from datetime import datetime, timedelta, timezone
from io import BytesIO
from typing import Any

from pydantic import TypeAdapter

from onyx.configs.constants import NUM_DAYS_TO_KEEP_CHECKPOINTS, FileOrigin
from onyx.connectors.outlook.models import (
    OutlookMailbox,
    ThreadCopy,
    ThreadGroup,
    ThreadListing,
)
from onyx.file_store.file_store import get_default_file_store

THREAD_DOCUMENT_ID_PREFIX = "outlook-thread:"
_ROOT_BYTES = 22
_FILE_PREFIX = "outlook-threads"
# Listing rows one build bucket holds in memory while its threads are grouped.
ROWS_PER_BUCKET = 20_000
# Rows buffered per bucket before a chunk file is written, and rows buffered
# across all buckets before the fullest one is written, so splitting the
# listing holds a bounded number of rows however many buckets there are.
BUCKET_FLUSH_ROWS = 1_000
BUCKET_BUFFER_ROWS = 50_000
_EXCLUSIONS = "exclusions.json"
_MANIFEST = "buckets.json"
_TOUCH = "touch.json"

_OLDEST = datetime.min.replace(tzinfo=timezone.utc)
_ROWS = TypeAdapter(list[ThreadListing])
_COUNTS = TypeAdapter(list[int])
_STRINGS = TypeAdapter(list[str])
_EXCLUSIONS_BY_MAILBOX = TypeAdapter(dict[str, list[str]])


def thread_key(conversation_index: str) -> str | None:
    """The thread a message belongs to, or None for an index Outlook did not set."""
    try:
        raw = base64.b64decode(conversation_index, validate=True)
    except (binascii.Error, ValueError):
        return None
    if len(raw) < _ROOT_BYTES:
        return None
    return base64.urlsafe_b64encode(raw[:_ROOT_BYTES]).decode().rstrip("=")


def thread_document_id(key: str) -> str:
    return f"{THREAD_DOCUMENT_ID_PREFIX}{key}"


def copy_document_id(key: str, mailbox: OutlookMailbox) -> str:
    """The document of one mailbox's own copy of a thread."""
    return f"{THREAD_DOCUMENT_ID_PREFIX}{key}:{mailbox.id}"


def _message_order(received: dict[str, datetime | None], message_id: str) -> tuple:
    return (received[message_id] or _OLDEST, message_id)


def group_threads(listings: Iterable[ThreadListing]) -> list[ThreadGroup]:
    """Listing rows folded into one group per thread, one copy per mailbox."""
    copies: dict[str, dict[str, ThreadCopy]] = {}
    for listing in listings:
        by_mailbox: dict[str, ThreadCopy] = copies.setdefault(listing.key, {})
        copy: ThreadCopy | None = by_mailbox.get(listing.mailbox.id)
        if copy is None:
            copy = ThreadCopy(
                mailbox=listing.mailbox, conversation_id=listing.conversation_id
            )
            by_mailbox[listing.mailbox.id] = copy
        copy.received[listing.message_id] = listing.received_at
    groups: list[ThreadGroup] = []
    for key, by_mailbox in copies.items():
        received: dict[str, datetime | None] = {}
        for copy in by_mailbox.values():
            received.update(copy.received)
        newest: str = max(received, key=lambda m: _message_order(received, m))
        groups.append(
            ThreadGroup(
                key=key, newest_message_id=newest, copies=list(by_mailbox.values())
            )
        )
    return groups


def candidate_copies(group: ThreadGroup) -> list[ThreadCopy]:
    """The copies the thread document may be built from: those holding the
    newest message. Every mailbox holding it was listed by the run that saw
    it, since a poll window covers every mailbox. Receipt times can differ by
    mailbox, so a message on the window's edge may be listed in one run for
    one mailbox and in the next for another, which grants fewer readers until
    the next permission sync, never more."""
    return [copy for copy in group.copies if group.newest_message_id in copy.received]


def partial_copies(
    group: ThreadGroup, readers: Iterable[OutlookMailbox]
) -> list[ThreadCopy]:
    """Copies that cannot read the thread document because they lack one of
    its messages. Each gets a document of its own copy."""
    reader_ids = {reader.id for reader in readers}
    return [copy for copy in group.copies if copy.mailbox.id not in reader_ids]


def choose_builder(candidates: Sequence[ThreadCopy]) -> ThreadCopy:
    """The copy with the most messages, the lowest mailbox id on a tie, so
    every run picks the same one."""
    return min(candidates, key=lambda copy: (-len(copy.received), copy.mailbox.id))


def newest_message_ids(copy: ThreadCopy, keep: int) -> set[str]:
    """The newest ``keep`` messages of the copy."""
    ordered = sorted(copy.received, key=lambda m: _message_order(copy.received, m))
    return set(ordered[-keep:])


def compared_window(copy: ThreadCopy, limit: int) -> ThreadCopy:
    """The copy cut to its newest ``limit`` messages. Both walks compare
    copies on this window, so a builder read through a capped outline and
    one read from the full listing come out the same."""
    kept = newest_message_ids(copy, limit)
    return copy.model_copy(
        update={"received": {m: at for m, at in copy.received.items() if m in kept}}
    )


def readers_of(
    candidates: Iterable[ThreadCopy], document_message_ids: set[str]
) -> list[OutlookMailbox]:
    """The mailboxes that hold every message the document holds."""
    return [
        copy.mailbox
        for copy in candidates
        if document_message_ids <= copy.received.keys()
    ]


class ThreadTable:
    """The attempt's listing, its build buckets and mailbox exclusions in the
    file store."""

    def __init__(self, run_id: str) -> None:
        self._prefix = f"{_FILE_PREFIX}/{run_id}/"
        self._chunk_counts: list[int] | None = None

    def _page_id(self, page: int) -> str:
        return f"{self._prefix}listing-{page}.json"

    def _chunk_id(self, bucket: int, chunk: int) -> str:
        return f"{self._prefix}bucket-{bucket}-{chunk}.json"

    def _mailbox_id(self, mailbox_id: str) -> str:
        return f"{self._prefix}mailbox-{mailbox_id}.json"

    def _write(self, file_id: str, payload: object) -> None:
        get_default_file_store().save_file(
            content=BytesIO(json.dumps(payload).encode()),
            display_name=file_id,
            file_origin=FileOrigin.INDEXING_CHECKPOINT,
            file_type="application/json",
            file_id=file_id,
        )

    def _read(self, file_id: str) -> bytes:
        return get_default_file_store().read_file(file_id, mode="b").read()

    def write_page(self, page: int, listings: Sequence[ThreadListing]) -> None:
        self._write(
            self._page_id(page), [row.model_dump(mode="json") for row in listings]
        )

    def iter_pages(self, page_count: int) -> Generator[ThreadListing, None, None]:
        """Every listing row, page by page, so no more than one page is held at once."""
        for page in range(page_count):
            yield from _ROWS.validate_json(self._read(self._page_id(page)))

    def write_buckets(self, page_count: int, row_count: int) -> int:
        """Splits the listing into buckets by thread key, so a bucket holds
        whole threads and about ROWS_PER_BUCKET rows, and folds the mailbox
        exclusions into one file. Returns the bucket count."""
        bucket_count: int = max(1, math.ceil(row_count / ROWS_PER_BUCKET))
        buffers: list[list[dict[str, Any]]] = [[] for _ in range(bucket_count)]
        chunk_counts: list[int] = [0] * bucket_count
        buffered = 0

        def flush(bucket: int) -> None:
            nonlocal buffered
            if not buffers[bucket]:
                return
            self._write(self._chunk_id(bucket, chunk_counts[bucket]), buffers[bucket])
            chunk_counts[bucket] += 1
            buffered -= len(buffers[bucket])
            buffers[bucket] = []

        for row in self.iter_pages(page_count):
            bucket: int = zlib.crc32(row.key.encode()) % bucket_count
            buffers[bucket].append(row.model_dump(mode="json"))
            buffered += 1
            if len(buffers[bucket]) >= BUCKET_FLUSH_ROWS:
                flush(bucket)
            elif buffered >= BUCKET_BUFFER_ROWS:
                flush(max(range(bucket_count), key=lambda b: len(buffers[b])))
        for bucket in range(bucket_count):
            flush(bucket)
        self._write(f"{self._prefix}{_MANIFEST}", chunk_counts)
        self._chunk_counts = chunk_counts
        self._write(f"{self._prefix}{_EXCLUSIONS}", self._collect_exclusions())
        return bucket_count

    def _collect_exclusions(self) -> dict[str, list[str]]:
        mailbox_prefix = f"{self._prefix}mailbox-"
        return {
            record.file_id[len(mailbox_prefix) : -len(".json")]: _STRINGS.validate_json(
                self._read(record.file_id)
            )
            for record in get_default_file_store().list_files_by_prefix(mailbox_prefix)
        }

    def read_bucket(self, bucket: int) -> list[ThreadListing]:
        if self._chunk_counts is None:
            self._chunk_counts = _COUNTS.validate_json(
                self._read(f"{self._prefix}{_MANIFEST}")
            )
        rows: list[ThreadListing] = []
        for chunk in range(self._chunk_counts[bucket]):
            rows.extend(_ROWS.validate_json(self._read(self._chunk_id(bucket, chunk))))
        return rows

    def write_mailbox_exclusions(self, mailbox_id: str, folder_ids: list[str]) -> None:
        self._write(self._mailbox_id(mailbox_id), folder_ids)

    def read_exclusions(self) -> dict[str, set[str]]:
        """Excluded folder ids by mailbox, as folded in by write_buckets."""
        return {
            mailbox_id: set(folder_ids)
            for mailbox_id, folder_ids in _EXCLUSIONS_BY_MAILBOX.validate_json(
                self._read(f"{self._prefix}{_EXCLUSIONS}")
            ).items()
        }

    def touch(self) -> None:
        """Marks the table as in use. A build pass only reads, so without
        this a long attempt would look abandoned to delete_abandoned_tables."""
        file_id = f"{self._prefix}{_TOUCH}"
        # The upsert keeps created_at, so the marker is recreated.
        get_default_file_store().delete_file(file_id, error_on_missing=False)
        self._write(file_id, [])

    def delete_all(self) -> None:
        file_store = get_default_file_store()
        for record in file_store.list_files_by_prefix(self._prefix):
            file_store.delete_file(record.file_id, error_on_missing=False)


def delete_abandoned_tables(days_to_keep: int = NUM_DAYS_TO_KEEP_CHECKPOINTS) -> None:
    """Drops the tables of attempts that never finished. A table is abandoned
    once nothing in it was written for longer than a checkpoint is resumable,
    so an attempt still stepping through its build keeps its table."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_to_keep)
    file_store = get_default_file_store()
    records = file_store.list_files_by_prefix(f"{_FILE_PREFIX}/")
    newest_write: dict[str, datetime] = {}
    for record in records:
        run: str = record.file_id.rsplit("/", 1)[0]
        newest_write[run] = max(newest_write.get(run, _OLDEST), record.created_at)
    for record in records:
        if newest_write[record.file_id.rsplit("/", 1)[0]] < cutoff:
            file_store.delete_file(record.file_id, error_on_missing=False)
