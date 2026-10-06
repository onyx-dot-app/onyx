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
from collections.abc import Callable, Iterable, Sequence
from datetime import datetime, timedelta, timezone
from io import BytesIO

from pydantic import TypeAdapter

from onyx.configs.constants import NUM_DAYS_TO_KEEP_CHECKPOINTS, FileOrigin
from onyx.connectors.outlook.models import (
    BucketManifest,
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
ROWS_PER_BUCKET = 50_000
# Rows buffered per bucket before a chunk file is written, and rows buffered
# across all buckets before the fullest one is written. Rows are held as their
# serialized lines, so the cap is a few hundred megabytes at most.
BUCKET_FLUSH_ROWS = 10_000
BUCKET_BUFFER_ROWS = 500_000
# Listing rows cut into buckets per step, so the cut stays resumable.
BUCKETING_ROWS_PER_STEP = 1_000_000
_EXCLUSIONS = "exclusions.json"
_MANIFEST = "buckets.json"
_TOUCH = "touch.json"

_OLDEST = datetime.min.replace(tzinfo=timezone.utc)
_ROWS = TypeAdapter(list[ThreadListing])
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


_KEY_PREFIX = b'{"key":"'


def _line_key(line: bytes) -> bytes:
    """The thread key of a serialized listing row, read without parsing it.
    ThreadListing puts ``key`` first, so the line opens with it."""
    if not line.startswith(_KEY_PREFIX):
        raise ValueError("A thread table row does not open with its key")
    return line[len(_KEY_PREFIX) : line.index(b'"', len(_KEY_PREFIX))]


def _rows(lines: Sequence[bytes]) -> list[ThreadListing]:
    return _ROWS.validate_json(b"[" + b",".join(lines) + b"]")


def bucket_count_for(row_count: int) -> int:
    """Buckets that keep each one near ROWS_PER_BUCKET listing rows."""
    return max(1, math.ceil(row_count / ROWS_PER_BUCKET))


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
        return f"{self._prefix}listing-{page}.jsonl"

    def _chunk_id(self, bucket: int, chunk: int) -> str:
        return f"{self._prefix}bucket-{bucket}-{chunk}.jsonl"

    def _mailbox_id(self, mailbox_id: str) -> str:
        return f"{self._prefix}mailbox-{mailbox_id}.json"

    def _save(self, file_id: str, content: bytes, file_type: str) -> None:
        get_default_file_store().save_file(
            content=BytesIO(content),
            display_name=file_id,
            file_origin=FileOrigin.INDEXING_CHECKPOINT,
            file_type=file_type,
            file_id=file_id,
        )

    def _write(self, file_id: str, payload: object) -> None:
        self._save(file_id, json.dumps(payload).encode(), "application/json")

    def _read(self, file_id: str) -> bytes:
        return get_default_file_store().read_file(file_id, mode="b").read()

    def _write_lines(self, file_id: str, lines: Sequence[bytes]) -> None:
        self._save(file_id, b"\n".join(lines), "application/x-ndjson")

    def _read_lines(self, file_id: str) -> list[bytes]:
        content: bytes = self._read(file_id)
        return content.split(b"\n") if content else []

    def write_page(self, page: int, listings: Sequence[ThreadListing]) -> None:
        """One row per line, so cutting into buckets moves lines without
        parsing them."""
        self._write_lines(
            self._page_id(page), [row.model_dump_json().encode() for row in listings]
        )

    def bucket_pages(self, first_page: int, page_count: int, bucket_count: int) -> int:
        """Cuts listing pages into buckets by thread key, from ``first_page``
        until BUCKETING_ROWS_PER_STEP rows are cut or the pages run out, so a
        bucket holds whole threads. Returns the page to continue from.

        The manifest records the pages already cut, so a step replayed after
        its manifest was written returns at once, and one replayed before, or
        from the first page, rewrites the same chunks."""
        manifest: BucketManifest | None = self._manifest() if first_page else None
        if manifest is None:
            manifest = BucketManifest(next_page=0, chunks=[0] * bucket_count)
        if manifest.next_page > first_page:
            return manifest.next_page
        buffers: list[list[bytes]] = [[] for _ in range(bucket_count)]
        buffered = 0
        cut: int = 0

        def flush(bucket: int) -> None:
            nonlocal buffered
            if not buffers[bucket]:
                return
            self._write_lines(
                self._chunk_id(bucket, manifest.chunks[bucket]), buffers[bucket]
            )
            manifest.chunks[bucket] += 1
            buffered -= len(buffers[bucket])
            buffers[bucket] = []

        page: int = first_page
        while page < page_count and cut < BUCKETING_ROWS_PER_STEP:
            lines: list[bytes] = self._read_lines(self._page_id(page))
            for line in lines:
                bucket: int = zlib.crc32(_line_key(line)) % bucket_count
                buffers[bucket].append(line)
                buffered += 1
                if len(buffers[bucket]) >= BUCKET_FLUSH_ROWS:
                    flush(bucket)
                elif buffered >= BUCKET_BUFFER_ROWS:
                    flush(max(range(bucket_count), key=lambda b: len(buffers[b])))
            cut += len(lines)
            page += 1
        for bucket in range(bucket_count):
            flush(bucket)
        manifest.next_page = page
        self._write_manifest(manifest)
        return page

    def write_buckets(
        self,
        page_count: int,
        row_count: int,
        on_step: Callable[[], None] | None = None,
    ) -> int:
        """Cuts the whole listing into buckets, calling ``on_step`` after
        each resumable step. Returns the bucket count."""
        bucket_count: int = bucket_count_for(row_count)
        page: int = 0
        while True:
            page = self.bucket_pages(page, page_count, bucket_count)
            if on_step is not None:
                on_step()
            if page >= page_count:
                return bucket_count

    def fold_exclusions(self) -> None:
        """Gathers the per-mailbox exclusion files into one, read once per build step."""
        self._write(f"{self._prefix}{_EXCLUSIONS}", self._collect_exclusions())

    def _manifest(self) -> BucketManifest:
        return BucketManifest.model_validate_json(
            self._read(f"{self._prefix}{_MANIFEST}")
        )

    def _write_manifest(self, manifest: BucketManifest) -> None:
        self._write(f"{self._prefix}{_MANIFEST}", manifest.model_dump(mode="json"))
        self._chunk_counts = manifest.chunks

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
            self._chunk_counts = self._manifest().chunks
        rows: list[ThreadListing] = []
        for chunk in range(self._chunk_counts[bucket]):
            rows.extend(_rows(self._read_lines(self._chunk_id(bucket, chunk))))
        return rows

    def write_mailbox_exclusions(self, mailbox_id: str, folder_ids: list[str]) -> None:
        self._write(self._mailbox_id(mailbox_id), folder_ids)

    def read_exclusions(self) -> dict[str, set[str]]:
        """Excluded folder ids by mailbox, as gathered by fold_exclusions."""
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
