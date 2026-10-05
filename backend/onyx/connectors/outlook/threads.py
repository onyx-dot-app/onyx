"""One document per mail thread, however many mailboxes hold a copy.

A thread is keyed by the root of its conversation index, the 22 bytes Outlook
sets on the first message and copies into every reply in every mailbox. The
conversation id cannot serve: the same message carries a different one in
each mailbox it was delivered to.

An index attempt lists every mailbox first, recording which mailboxes hold
each thread, then builds each thread once from the first mailbox that listed
it, readable by every holder. The listing is too large for the checkpoint,
which is written after every step, so it lives in the file store under the
attempt's run id: one page per listing step, then one shard per build step,
plus one file per opened mailbox with its excluded folder ids.
"""

import base64
import binascii
import json
from collections.abc import Generator, Iterable, Sequence
from datetime import datetime, timedelta, timezone
from io import BytesIO
from typing import Any

from pydantic import BaseModel

from onyx.configs.constants import NUM_DAYS_TO_KEEP_CHECKPOINTS, FileOrigin
from onyx.connectors.outlook.models import OutlookMailbox
from onyx.file_store.file_store import get_default_file_store

THREAD_DOCUMENT_ID_PREFIX = "outlook-thread:"
_ROOT_BYTES = 22
_FILE_PREFIX = "outlook-threads"


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


class ThreadEntry(BaseModel):
    """A thread to build: read from the first mailbox that listed it, readable
    by every mailbox that holds it."""

    key: str
    first: ThreadListing
    holders: list[OutlookMailbox]


def merge_listings(listings: Iterable[ThreadListing]) -> list[ThreadEntry]:
    """Listings in the order they were recorded, folded into one entry per
    thread. The first listing of a thread is the copy the thread is built from."""
    entries: dict[str, ThreadEntry] = {}
    holder_ids: dict[str, set[str]] = {}
    for listing in listings:
        entry = entries.get(listing.key)
        if entry is None:
            entry = ThreadEntry(key=listing.key, first=listing, holders=[])
            entries[listing.key] = entry
            holder_ids[listing.key] = set()
        if listing.mailbox.id in holder_ids[listing.key]:
            continue
        holder_ids[listing.key].add(listing.mailbox.id)
        entry.holders.append(listing.mailbox)
    return list(entries.values())


class ThreadTable:
    """The attempt's listings, build shards and mailbox exclusions in the file store."""

    def __init__(self, run_id: str) -> None:
        self._prefix = f"{_FILE_PREFIX}/{run_id}/"

    def _page_id(self, page: int) -> str:
        return f"{self._prefix}listing-{page}.json"

    def _shard_id(self, shard: int) -> str:
        return f"{self._prefix}shard-{shard}.json"

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
        rows = json.loads(get_default_file_store().read_file(file_id, mode="b").read())
        if not isinstance(rows, list):
            raise ValueError(f"{file_id} does not hold a list")
        return rows

    def write_page(self, page: int, listings: Sequence[ThreadListing]) -> None:
        self._write(
            self._page_id(page), [row.model_dump(mode="json") for row in listings]
        )

    def iter_pages(self, page_count: int) -> Generator[ThreadListing, None, None]:
        """Every listing, page by page, so no more than one page is held at once."""
        for page in range(page_count):
            for row in self._read(self._page_id(page)):
                yield ThreadListing.model_validate(row)

    def write_shards(self, entries: Sequence[ThreadEntry], per_shard: int) -> int:
        """Writes the entries in shards of ``per_shard`` and returns the shard count."""
        shard_count = 0
        for start in range(0, len(entries), per_shard):
            rows = [
                row.model_dump(mode="json")
                for row in entries[start : start + per_shard]
            ]
            self._write(self._shard_id(shard_count), rows)
            shard_count += 1
        return shard_count

    def read_shard(self, shard: int) -> list[ThreadEntry]:
        return [
            ThreadEntry.model_validate(row) for row in self._read(self._shard_id(shard))
        ]

    def write_mailbox_exclusions(self, mailbox_id: str, folder_ids: list[str]) -> None:
        self._write(self._mailbox_id(mailbox_id), folder_ids)

    def read_mailbox_exclusions(self, mailbox_id: str) -> set[str]:
        return {
            str(folder_id) for folder_id in self._read(self._mailbox_id(mailbox_id))
        }

    def delete_all(self) -> None:
        file_store = get_default_file_store()
        for record in file_store.list_files_by_prefix(self._prefix):
            file_store.delete_file(record.file_id, error_on_missing=False)


def delete_abandoned_tables(days_to_keep: int = NUM_DAYS_TO_KEEP_CHECKPOINTS) -> None:
    """Drops the tables of attempts that never finished. A checkpoint older
    than this is never resumed, so its table cannot be read again either."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_to_keep)
    file_store = get_default_file_store()
    for record in file_store.list_files_by_prefix(f"{_FILE_PREFIX}/"):
        if record.created_at < cutoff:
            file_store.delete_file(record.file_id, error_on_missing=False)
