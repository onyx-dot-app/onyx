"""One document per mail thread, decided from message headers alone.

A thread is keyed by the root of its conversation index, which Outlook sets
on the first message and copies into every reply in every mailbox. Messages
are matched across mailboxes by Internet Message-ID. Every mailbox decides
its part of a thread from its own copy, so the walks share no state: the
first message names the builder, whose copy is the thread document, and
``plan_documents`` spells out who reads it and what the other holders write.
"""

import base64
import binascii
from collections.abc import Callable, Iterable, Sequence
from datetime import datetime, timezone

from onyx.connectors.outlook.models import (
    DocumentPlan,
    OutlookMailbox,
    OutlookMessageChange,
    ThreadListing,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

THREAD_DOCUMENT_ID_PREFIX = "outlook-thread:"
OWN_DOCUMENT_SUFFIX = ":own"
_ROOT_BYTES = 22

# A conversation longer than this keeps only its newest indexable messages.
MAX_MESSAGES_PER_CONVERSATION = 100

_OLDEST = datetime.min.replace(tzinfo=timezone.utc)

# The run's mailboxes by lower-cased address, so a message's headers map to
# the mailboxes the run walks.
Roster = dict[str, OutlookMailbox]


def _conversation_root(conversation_index: str) -> bytes | None:
    try:
        raw = base64.b64decode(conversation_index, validate=True)
    except (binascii.Error, ValueError):
        return None
    if len(raw) < _ROOT_BYTES:
        return None
    return raw


def thread_key(conversation_index: str) -> str | None:
    """The thread a message belongs to, or None for an index Outlook did not set."""
    raw = _conversation_root(conversation_index)
    if raw is None:
        return None
    return base64.urlsafe_b64encode(raw[:_ROOT_BYTES]).decode().rstrip("=")


def is_thread_root(conversation_index: str) -> bool:
    """True for the thread's first message, whose index carries no reply blocks."""
    raw = _conversation_root(conversation_index)
    return raw is not None and len(raw) == _ROOT_BYTES


def thread_document_id(key: str) -> str:
    return f"{THREAD_DOCUMENT_ID_PREFIX}{key}"


def copy_document_id(key: str, mailbox: OutlookMailbox) -> str:
    """The document the builder writes for a mailbox named on the first
    message but not on every one."""
    return f"{THREAD_DOCUMENT_ID_PREFIX}{key}:{mailbox.id}"


def own_document_id(key: str, mailbox: OutlookMailbox) -> str:
    """The document a mailbox writes for what the builder cannot see of its copy."""
    return f"{copy_document_id(key, mailbox)}{OWN_DOCUMENT_SUFFIX}"


def roster_of(mailboxes: Iterable[OutlookMailbox]) -> Roster:
    return {mailbox.address.lower(): mailbox for mailbox in mailboxes}


def listing_row(change: OutlookMessageChange, roster: Roster) -> ThreadListing | None:
    """The listing row for one message copy. None for a removal, a draft, or a
    message Outlook set no conversation index on."""
    if change.removed or change.is_draft or not change.conversation_id:
        return None
    index = change.conversation_index or ""
    key = thread_key(index)
    if key is None:
        logger.warning(
            "Outlook: message %s has no conversation index, skipping", change.id
        )
        return None
    sender: OutlookMailbox | None = (
        roster.get(change.sender.address.lower()) if change.sender else None
    )
    named: dict[str, OutlookMailbox] = {}
    if sender is not None:
        named[sender.id] = sender
    for recipient in [*change.to_recipients, *change.cc_recipients]:
        mailbox = roster.get(recipient.address.lower())
        if mailbox is not None:
            named.setdefault(mailbox.id, mailbox)
    return ThreadListing(
        key=key,
        conversation_id=change.conversation_id,
        message_id=change.match_id,
        received_at=change.received_at,
        is_root=is_thread_root(index),
        sender=sender,
        named=list(named.values()),
    )


def _row_order(row: ThreadListing) -> tuple[datetime, str]:
    return (row.received_at or _OLDEST, row.message_id)


def newest_rows(rows: Iterable[ThreadListing], keep: int) -> list[ThreadListing]:
    """The newest ``keep`` messages of a copy, oldest first, each message once
    however many times the listing saw it."""
    unique: dict[str, ThreadListing] = {}
    for row in rows:
        unique.setdefault(row.message_id, row)
    return sorted(unique.values(), key=_row_order)[-keep:]


# Whether the run can open a mailbox. A directory user without a usable
# mailbox, a guest or an unlicensed member, is in the roster but never walks.
IsAvailable = Callable[[OutlookMailbox], bool]


def designated_builder(
    root: ThreadListing, is_available: IsAvailable
) -> OutlookMailbox | None:
    """The mailbox that writes the thread document: the first message's
    sender when the run walks it, else the lowest mailbox id it names, so
    every holder picks the same one. A mailbox the run cannot open is passed
    over, since it would never build. None when nothing named can."""
    candidates: list[OutlookMailbox] = sorted(root.named, key=lambda m: m.id)
    if root.sender is not None:
        candidates.insert(0, root.sender)
    return next((m for m in candidates if is_available(m)), None)


def _named_ids(row: ThreadListing) -> set[str]:
    return {mailbox.id for mailbox in row.named}


def _message_ids(rows: Iterable[ThreadListing]) -> list[str]:
    return [row.message_id for row in rows]


def plan_documents(
    rows: Sequence[ThreadListing], mailbox: OutlookMailbox, is_available: IsAvailable
) -> list[DocumentPlan]:
    """The documents one mailbox's copy of a thread yields. Indexing fetches
    the bodies for them, the slim walk lists their ids and readers, so both
    agree.

    The first message's sender builds the thread document from its copy,
    readable by the mailboxes named on every message in it, and writes a
    mailbox the first message names but a later one left out the messages
    that name it. Everything the builder cannot see, a copy without the first
    message, a thread whose first message names no walked mailbox, a holder
    it does not name, or a reply that left the builder out, is its own
    mailbox's own document. The builder's copy of the first message is in its
    Sent Items, so excluding that folder leaves the threads a mailbox started
    to its own documents of the replies."""
    kept = newest_rows(rows, MAX_MESSAGES_PER_CONVERSATION)
    if not kept:
        return []
    key = kept[0].key
    roots = [row for row in rows if row.is_root]
    root = min(roots, key=_row_order) if roots else None
    builder = designated_builder(root, is_available) if root is not None else None
    if root is not None and builder is not None and builder.id == mailbox.id:
        return _builder_documents(key, kept, root, mailbox)
    if root is None or builder is None or mailbox.id not in _named_ids(root):
        own = kept
    else:
        own = [row for row in kept if builder.id not in _named_ids(row)]
    if not own:
        return []
    return [
        DocumentPlan(
            document_id=own_document_id(key, mailbox),
            message_ids=_message_ids(own),
            readers=[mailbox],
        )
    ]


def _builder_documents(
    key: str, kept: list[ThreadListing], root: ThreadListing, builder: OutlookMailbox
) -> list[DocumentPlan]:
    """The thread document, readable by the mailboxes named on every kept
    message, plus one document per mailbox the first message names that a
    later message left out."""
    named_everywhere: set[str] = set.intersection(*(_named_ids(row) for row in kept))
    readers: dict[str, OutlookMailbox] = {builder.id: builder}
    for row in kept:
        for reader in row.named:
            if reader.id in named_everywhere:
                readers.setdefault(reader.id, reader)
    plans = [
        DocumentPlan(
            document_id=thread_document_id(key),
            message_ids=_message_ids(kept),
            readers=list(readers.values()),
        )
    ]
    for participant in sorted(root.named, key=lambda m: m.id):
        if participant.id in readers:
            continue
        theirs = [row for row in kept if participant.id in _named_ids(row)]
        if not theirs:
            continue
        plans.append(
            DocumentPlan(
                document_id=copy_document_id(key, participant),
                message_ids=_message_ids(theirs),
                readers=[participant],
            )
        )
    return plans
