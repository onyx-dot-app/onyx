"""One document per mail thread, however many mailboxes hold a copy.

A thread is keyed by the root of its conversation index, the 22 bytes Outlook
sets on the first message and copies into every reply in every mailbox. The
conversation id cannot serve: the same message carries a different one in
each mailbox it was delivered to. Messages are matched across mailboxes by
their Internet Message-ID, which every copy shares.

Copies of a thread differ: a reply sent to one person sits in two mailboxes
while the rest hold the earlier messages only. The thread document is built
from the copy that holds the thread's newest message and the most messages,
and it is readable only by the mailboxes that hold every message in it. Every
other mailbox gets a document of its own copy instead, readable by its owner
alone. Indexing and the slim walk apply the same rules, so pruning and the
permission sync never disagree with the index.

Any run that lists a thread's newest message lists every mailbox that holds
it, because a poll window covers every mailbox, so the readers come out the
same from a poll window as from a full listing. A mailbox that holds only
older messages and gained none this window is not visited, so its own
document waits for a run that lists it again.

An index attempt lists every mailbox first, recording each message copy, then
builds each thread once. The listing is too large for the checkpoint, which
is written after every step, so it lives in the file store under the
attempt's run id: one page per listing step, then one bucket of threads per
build pass, plus one file per opened mailbox with its excluded folder ids.
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
# Rows buffered per bucket before a chunk file is written, so splitting the
# listing into buckets holds at most this many rows per bucket in memory.
BUCKET_FLUSH_ROWS = 1_000
_MANIFEST = "buckets.json"
_TOUCH = "touch.json"

_OLDEST = datetime.min.replace(tzinfo=timezone.utc)


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
        by_mailbox = copies.setdefault(listing.key, {})
        copy = by_mailbox.get(listing.mailbox.id)
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
        newest = max(received, key=lambda m: _message_order(received, m))
        groups.append(
            ThreadGroup(
                key=key, newest_message_id=newest, copies=list(by_mailbox.values())
            )
        )
    return groups


def candidate_copies(group: ThreadGroup) -> list[ThreadCopy]:
    """The copies the thread document may be built from: those holding the
    newest message. Every mailbox holding it was listed by the run that saw it."""
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
    """The messages a document built from this copy holds."""
    ordered = sorted(copy.received, key=lambda m: _message_order(copy.received, m))
    return set(ordered[-keep:])


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

    def _read(self, file_id: str) -> list[Any]:
        rows: Any = json.loads(
            get_default_file_store().read_file(file_id, mode="b").read()
        )
        if not isinstance(rows, list):
            raise ValueError(f"{file_id} does not hold a list")
        return rows

    def write_page(self, page: int, listings: Sequence[ThreadListing]) -> None:
        self._write(
            self._page_id(page), [row.model_dump(mode="json") for row in listings]
        )

    def iter_pages(self, page_count: int) -> Generator[ThreadListing, None, None]:
        """Every listing row, page by page, so no more than one page is held at once."""
        for page in range(page_count):
            for row in self._read(self._page_id(page)):
                yield ThreadListing.model_validate(row)

    def write_buckets(self, page_count: int, row_count: int) -> int:
        """Splits the listing into buckets by thread key, so a bucket holds
        whole threads and about ROWS_PER_BUCKET rows. Returns the bucket count."""
        bucket_count: int = max(1, math.ceil(row_count / ROWS_PER_BUCKET))
        buffers: list[list[dict[str, Any]]] = [[] for _ in range(bucket_count)]
        chunk_counts: list[int] = [0] * bucket_count

        def flush(bucket: int) -> None:
            if not buffers[bucket]:
                return
            self._write(self._chunk_id(bucket, chunk_counts[bucket]), buffers[bucket])
            chunk_counts[bucket] += 1
            buffers[bucket] = []

        for row in self.iter_pages(page_count):
            bucket = zlib.crc32(row.key.encode()) % bucket_count
            buffers[bucket].append(row.model_dump(mode="json"))
            if len(buffers[bucket]) >= BUCKET_FLUSH_ROWS:
                flush(bucket)
        for bucket in range(bucket_count):
            flush(bucket)
        self._write(f"{self._prefix}{_MANIFEST}", chunk_counts)
        self._chunk_counts = chunk_counts
        return bucket_count

    def read_bucket(self, bucket: int) -> list[ThreadListing]:
        if self._chunk_counts is None:
            self._chunk_counts = [
                int(count) for count in self._read(f"{self._prefix}{_MANIFEST}")
            ]
        rows: list[ThreadListing] = []
        for chunk in range(self._chunk_counts[bucket]):
            rows.extend(
                ThreadListing.model_validate(row)
                for row in self._read(self._chunk_id(bucket, chunk))
            )
        return rows

    def write_mailbox_exclusions(self, mailbox_id: str, folder_ids: list[str]) -> None:
        self._write(self._mailbox_id(mailbox_id), folder_ids)

    def read_mailbox_exclusions(self, mailbox_id: str) -> set[str]:
        return {
            str(folder_id) for folder_id in self._read(self._mailbox_id(mailbox_id))
        }

    def touch(self) -> None:
        """Marks the table as in use. A build pass only reads, so without
        this a long attempt would look abandoned to delete_abandoned_tables."""
        file_id = f"{self._prefix}{_TOUCH}"
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
        run_prefix = record.file_id.rsplit("/", 1)[0]
        newest_write[run_prefix] = max(
            newest_write.get(run_prefix, record.created_at), record.created_at
        )
    for record in records:
        if newest_write[record.file_id.rsplit("/", 1)[0]] < cutoff:
            file_store.delete_file(record.file_id, error_on_missing=False)
