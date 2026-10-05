"""One document per mail thread, however many mailboxes hold a copy.

A thread is keyed by the root of its conversation index, the 22 bytes Outlook
sets on the first message and copies into every reply in every mailbox. The
conversation id cannot serve: the same message carries a different one in
each mailbox it was delivered to.

An index attempt lists every mailbox first, recording which mailboxes hold
each thread, then builds each thread once from the first mailbox that listed
it, readable by every holder. The listing is too large for the checkpoint,
which is written after every step, so it lives in the file store under the
attempt's run id: one page per listing step, then one shard per build step.
"""

import base64
import binascii
import json
from collections import defaultdict
from io import BytesIO

from pydantic import BaseModel

from onyx.configs.constants import FileOrigin
from onyx.connectors.outlook.models import OutlookMailbox
from onyx.file_store.file_store import get_default_file_store
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel

THREAD_DOCUMENT_ID_PREFIX = "outlook-thread:"
_ROOT_BYTES = 22
_FILE_PREFIX = "outlook-threads"
# Pages are read back together, so the reads run side by side.
_PAGE_READ_WORKERS = 16


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


class ThreadListing(BaseModel):
    """One mailbox's copy of a thread, as the delta listing saw it."""

    key: str
    mailbox: OutlookMailbox
    conversation_id: str
    folder_id: str


class ThreadEntry(BaseModel):
    """A thread to build: read from the first mailbox that listed it, readable
    by every mailbox that holds it."""

    key: str
    first: ThreadListing
    holders: list[OutlookMailbox]


def merge_listings(listings: list[ThreadListing]) -> list[ThreadEntry]:
    """Listings in the order they were recorded, folded into one entry per
    thread. The first listing of a thread is the copy the thread is built from."""
    entries: dict[str, ThreadEntry] = {}
    holder_ids: dict[str, set[str]] = defaultdict(set)
    for listing in listings:
        entry = entries.get(listing.key)
        if entry is None:
            entry = ThreadEntry(key=listing.key, first=listing, holders=[])
            entries[listing.key] = entry
        if listing.mailbox.id in holder_ids[listing.key]:
            continue
        holder_ids[listing.key].add(listing.mailbox.id)
        entry.holders.append(listing.mailbox)
    return list(entries.values())


class ThreadTable:
    """The attempt's listings and build shards in the file store."""

    def __init__(self, run_id: str) -> None:
        self._prefix = f"{_FILE_PREFIX}/{run_id}/"

    def _page_id(self, page: int) -> str:
        return f"{self._prefix}listing-{page}.json"

    def _shard_id(self, shard: int) -> str:
        return f"{self._prefix}shard-{shard}.json"

    def _write(self, file_id: str, rows: list[BaseModel]) -> None:
        payload = json.dumps([row.model_dump(mode="json") for row in rows]).encode()
        get_default_file_store().save_file(
            content=BytesIO(payload),
            display_name=file_id,
            file_origin=FileOrigin.INDEXING_CHECKPOINT,
            file_type="application/json",
            file_id=file_id,
        )

    def _read(self, file_id: str) -> list[dict]:
        return json.loads(get_default_file_store().read_file(file_id, mode="b").read())

    def write_page(self, page: int, listings: list[ThreadListing]) -> None:
        self._write(self._page_id(page), list(listings))

    def read_pages(self, pages: int) -> list[ThreadListing]:
        results: list[list[dict]] = run_functions_tuples_in_parallel(
            [(self._read, (self._page_id(page),)) for page in range(pages)],
            max_workers=_PAGE_READ_WORKERS,
        )
        return [ThreadListing.model_validate(row) for rows in results for row in rows]

    def write_shards(self, entries: list[ThreadEntry], per_shard: int) -> int:
        """Writes the entries in shards of ``per_shard`` and returns the shard count."""
        shards = [entries[i : i + per_shard] for i in range(0, len(entries), per_shard)]
        for shard, rows in enumerate(shards):
            self._write(self._shard_id(shard), list(rows))
        return len(shards)

    def read_shard(self, shard: int) -> list[ThreadEntry]:
        return [
            ThreadEntry.model_validate(row) for row in self._read(self._shard_id(shard))
        ]

    def delete_all(self) -> None:
        file_store = get_default_file_store()
        for record in file_store.list_files_by_prefix(self._prefix):
            file_store.delete_file(record.file_id, error_on_missing=False)
