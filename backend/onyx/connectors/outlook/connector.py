"""Outlook connector: Microsoft 365 mail and calendar over Graph.

One document per mail thread by the header rules in ``threads.py``, and with
calendars on, one per event or recurring series per mailbox. Every Graph call
goes through ``OutlookSourceOperations``.

Each mailbox is walked on its own, a few side by side. Its folders are read
through delta pages of message metadata, headers included, one page per
checkpoint step, and the rows are held in memory until the last folder is
done. Each conversation is then decided from that copy alone and the bodies
of the messages its documents need are read.

Incremental runs come from the poll window rather than saved delta links: an
index attempt starts from a fresh checkpoint, so each folder's delta round
opens with ``receivedDateTime ge start`` and any conversation that gained a
message in the window is read whole through its outline and rebuilt.

Pruning walks the same mailboxes, folders and calendar windows but reads only
metadata, so a thread deleted from every mailbox leaves the index without a
full re-index. A thread that lost one message keeps the stale text until it
gains a message or a full re-index rebuilds it.
"""

from collections import deque
from collections.abc import Callable, Generator, Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from io import BytesIO
from typing import Any, TypeVar
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from babel.core import get_global
from pydantic import model_validator

from onyx.access.models import ExternalAccess
from onyx.configs.app_configs import (
    INDEX_BATCH_SIZE,
    OUTLOOK_CONNECTOR_ATTACHMENT_SIZE_THRESHOLD,
)
from onyx.configs.constants import DocumentSource
from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.cross_connector_utils.rate_limit_wrapper import (
    RateLimitTriedTooManyTimesError,
)
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.interfaces import (
    CheckpointedConnectorWithPermSync,
    CheckpointOutput,
    CredentialsConnector,
    CredentialsProviderInterface,
    GenerateSlimDocumentOutput,
    SecondsSinceUnixEpoch,
    SlimConnector,
    SlimConnectorWithPermSync,
)
from onyx.connectors.microsoft_utils.config import (
    DEFAULT_AUTHORITY_HOST,
    DEFAULT_GRAPH_API_HOST,
)
from onyx.connectors.microsoft_utils.drive_items import SizeCapExceeded
from onyx.connectors.microsoft_utils.entra import EntraGroup
from onyx.connectors.microsoft_utils.graph_env import resolve_microsoft_environment
from onyx.connectors.microsoft_utils.graph_errors import (
    MicrosoftAuthError as OutlookAuthError,
)
from onyx.connectors.microsoft_utils.graph_errors import (
    MicrosoftGraphError as OutlookGraphError,
)
from onyx.connectors.microsoft_utils.graph_errors import raise_for_auth_error
from onyx.connectors.models import (
    BasicExpertInfo,
    ConnectorCheckpoint,
    ConnectorFailure,
    ConnectorMissingCredentialError,
    Document,
    EntityFailure,
    HierarchyNode,
    SlimDocument,
    TextSection,
)
from onyx.connectors.outlook.config import (
    DEFAULT_CALENDAR_FUTURE_DAYS,
    DEFAULT_CALENDAR_PAST_DAYS,
)
from onyx.connectors.outlook.errors import (
    CALENDAR_READ_REMEDIATION,
    EXCHANGE_SCOPE_REMEDIATION,
    GROUP_UNAVAILABLE_REMEDIATION,
    MAILBOX_UNAVAILABLE_REMEDIATION,
    raise_for_graph_error,
)
from onyx.connectors.outlook.mailboxes import (
    clean_names,
    describe_group_mismatch,
    describe_unavailable_groups,
    describe_unavailable_mailboxes,
    raise_if_groups_unavailable,
    raise_if_unavailable,
)
from onyx.connectors.outlook.models import (
    EVENT_OCCURRENCE,
    DocumentPlan,
    MailboxCursor,
    MailboxStep,
    OutlookAttachment,
    OutlookEvent,
    OutlookFolder,
    OutlookMailbox,
    OutlookMailboxPage,
    OutlookMessage,
    OutlookMessageChange,
    OutlookMessageIdentity,
    OutlookRecipient,
    ThreadListing,
)
from onyx.connectors.outlook.source_operations import (
    CONFIG_AUTHORITY_HOST,
    CONFIG_GRAPH_API_HOST,
    OutlookSourceOperations,
)
from onyx.connectors.outlook.threads import (
    Roster,
    listing_row,
    plan_documents,
    roster_of,
)
from onyx.db.enums import HierarchyNodeType
from onyx.file_processing.extract_file_text import (
    extract_file_text_locally,
    get_file_ext,
)
from onyx.file_processing.file_types import OnyxFileExtensions
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger
from onyx.utils.process_isolation import run_in_isolated_process
from onyx.utils.threadpool_concurrency import (
    parallel_yield,
    run_functions_tuples_in_parallel,
)

logger = setup_logger()

# Document ids per batch handed to pruning.
SLIM_BATCH_SIZE = 500

# Skipped by default. Resolved by well-known name per mailbox, because display
# names are localized and an admin's exclusion list is not.
DEFAULT_EXCLUDED_WELL_KNOWN_FOLDERS = ("junkemail", "deleteditems", "drafts", "outbox")

# Indexable messages an outline reads per conversation, so a thread that is
# mostly drafts or trashed replies stays bounded.
CONVERSATION_FETCH_LIMIT = 500
# Raw messages read while outlining a copy and fetching the chosen ones. Wide
# enough that the window is the newest indexable messages, not the raw ones.
COMPARED_FETCH_LIMIT = CONVERSATION_FETCH_LIMIT * 10

# Conversations of one mailbox built at a time. Exchange throttles per mailbox,
# so the parallelism that pays is across mailboxes, not within one.
CONVERSATION_BUILD_WORKERS = 4
# Conversations per mailbox per build step, so a step stays short and its
# checkpoint cheap.
CONVERSATIONS_PER_STEP = 25

# Mailboxes walked side by side. Exchange throttles per app and mailbox, so
# separate mailboxes do not slow one another.
MAILBOX_WORKERS = 8
# Listing rows one mailbox may hold in memory, a few hundred megabytes at
# most across the mailboxes in flight. A mailbox past it is skipped by
# indexing and fails a slim walk, since its threads cannot be decided whole.
MAX_LISTING_ROWS_PER_MAILBOX = 250_000

# Series ids the checkpoint carries across all active mailboxes. It is
# written after every step, so the per-mailbox cap shrinks as more mailboxes run.
TRACKED_SERIES_PER_STEP = 5_000

# Pages of a mailbox listing, the tenant's users or a group's members, one
# step may read. No tenant has this many users, so running past it means the
# paging never ends.
MAX_MAILBOX_LISTING_PAGES = 10_000

# Attachment bytes come from whoever sent the mail, so what one message and
# one conversation can cost is capped however far the files expand or however
# many of them fail.
MAX_ATTACHMENTS_PER_MESSAGE = 20
MAX_ATTACHMENT_TEXT_PER_CONVERSATION = 1_000_000
MAX_ATTACHMENT_READS_PER_CONVERSATION = 25

# The deadline of the child process that parses an attachment, PDFium and the
# pypdf fallback included.
ATTACHMENT_EXTRACTION_TIMEOUT_SECONDS = 120


# Graph stops a filtered delta round at this many messages without saying so.
# A folder that fills the cap is read again without the filter, which has no
# cap, and the poll window is applied to each entry here instead.
FILTERED_DELTA_CAP = 5000

THROTTLED_STATUS = 429
THROTTLED_MESSAGE = (
    "Microsoft Graph is rate limiting this connector. It resumes from its "
    "checkpoint on the next run."
)

MAILBOX_NODE_PREFIX = "outlook-mailbox:"
CALENDAR_NODE_PREFIX = "outlook-calendar:"
EVENT_DOCUMENT_ID_PREFIX = "outlook-event:"

# Attendee names written into an event's text. A company all-hands lists
# hundreds and the rest add nothing a search would find.
MAX_ATTENDEES_LISTED = 50
# Series ids a mailbox remembers this attempt so each master is read once.
# Past this many, later series are read again per occurrence instead of
# growing the checkpoint with the size of the calendar.
MAX_TRACKED_SERIES_PER_MAILBOX = TRACKED_SERIES_PER_STEP // MAILBOX_WORKERS
# Private hides an event's details from anyone the calendar is shared with,
# and confidential flags it as not for wider eyes. Neither belongs in a shared
# index.
SKIPPED_EVENT_SENSITIVITIES = frozenset({"private", "confidential"})


class _MailboxListing:
    """One mailbox's listing rows while its folders are read, then its
    conversations in listing order once they are. Lives in the process that
    listed the mailbox, never in the checkpoint, so its size is bounded by
    one mailbox, not the tenant."""

    def __init__(self) -> None:
        self.rows: list[ThreadListing] = []
        self.conversations: list[list[ThreadListing]] = []
        self.grouped = False

    def group(self) -> None:
        by_conversation: dict[str, list[ThreadListing]] = {}
        for row in self.rows:
            by_conversation.setdefault(row.conversation_id, []).append(row)
        self.conversations = list(by_conversation.values())
        self.rows = []
        self.grouped = True


class OutlookCheckpoint(ConnectorCheckpoint):
    # None until enumerated, then the mailboxes not yet started, popped from the end.
    mailboxes: list[OutlookMailbox] | None = None
    # The mailboxes being walked, at most MAILBOX_WORKERS of them.
    active: list[MailboxCursor] = []

    @model_validator(mode="before")
    @classmethod
    def _adopt_single_mailbox_shape(cls, data: Any) -> Any:
        """A checkpoint saved with one current mailbox at the top level, the
        shape before cursors, loads as one active cursor, so an attempt in
        flight across a deploy resumes without losing progress."""
        if not isinstance(data, dict):
            return data
        # The table-based shape kept its listing in a store this connector
        # no longer reads, so such an attempt starts over.
        if "listing_pages" in data:
            return {"has_more": True}
        if not data.get("current_mailbox"):
            return data
        cursor: dict[str, Any] = {
            name: data[name] for name in MailboxCursor.model_fields if name in data
        }
        cursor["mailbox"] = data["current_mailbox"]
        cursor["opened"] = True
        cursor["folders"] = data.get("folders") or []
        # The old shape tracked a whole step's worth per mailbox. Keep the
        # newest within the per-mailbox cap so the cursor is not oversized.
        seen_series: list[str] = list(data.get("seen_series_ids") or [])
        cursor["seen_series_ids"] = set(seen_series[-MAX_TRACKED_SERIES_PER_MAILBOX:])
        kept: dict[str, Any] = {
            name: value
            for name, value in data.items()
            if name in ("has_more", "mailboxes")
        }
        return kept | {"active": [cursor]}


def mailbox_node_id(mailbox: OutlookMailbox) -> str:
    return f"{MAILBOX_NODE_PREFIX}{mailbox.id}"


def calendar_node_id(mailbox: OutlookMailbox) -> str:
    return f"{CALENDAR_NODE_PREFIX}{mailbox.id}"


def event_document_id(mailbox: OutlookMailbox, event_id: str) -> str:
    """Keyed by mailbox like conversations: every attendee's mailbox holds its
    own copy of a meeting, each with its own readership."""
    return f"{EVENT_DOCUMENT_ID_PREFIX}{mailbox.id}:{event_id}"


def _mailbox_link(mailbox: OutlookMailbox) -> str:
    return f"https://outlook.office.com/mail/{mailbox.address}/"


def _calendar_link(mailbox: OutlookMailbox) -> str:
    return f"https://outlook.office.com/calendar/{mailbox.address}/"


def _mailbox_failure(
    address: str, message: str, exception: Exception | None = None
) -> ConnectorFailure:
    return ConnectorFailure(
        failed_entity=EntityFailure(entity_id=address),
        failure_message=message,
        exception=exception,
    )


def _oversized_mailbox_message(mailbox: OutlookMailbox) -> str:
    return (
        f"Mailbox {mailbox.address} holds more than "
        f"{MAX_LISTING_ROWS_PER_MAILBOX} messages, more than the connector "
        "decides in memory. Exclude its largest folders or leave it out."
    )


def _oversized_mailbox_failure(mailbox: OutlookMailbox) -> ConnectorFailure:
    return _mailbox_failure(mailbox.address, _oversized_mailbox_message(mailbox))


def _format_recipient(recipient: OutlookRecipient) -> str:
    if recipient.name and recipient.name != recipient.address:
        return f"{recipient.name} <{recipient.address}>"
    return recipient.address


def _message_sort_key(message: OutlookMessage) -> datetime:
    return (
        message.received_at
        or message.sent_at
        or datetime.min.replace(tzinfo=timezone.utc)
    )


def _message_section(message: OutlookMessage) -> TextSection:
    lines: list[str] = []
    if message.sender is not None:
        lines.append(f"From: {_format_recipient(message.sender)}")
    if message.to_recipients:
        lines.append(
            "To: " + ", ".join(_format_recipient(r) for r in message.to_recipients)
        )
    if message.cc_recipients:
        lines.append(
            "Cc: " + ", ".join(_format_recipient(r) for r in message.cc_recipients)
        )
    sent_at = message.sent_at or message.received_at
    if sent_at is not None:
        lines.append(f"Date: {sent_at.isoformat()}")
    if message.subject:
        lines.append(f"Subject: {message.subject}")
    header = "\n".join(lines)
    text = f"{header}\n\n{message.body_text}" if header else message.body_text
    return TextSection(link=message.web_link, text=text.strip())


def _expert(recipient: OutlookRecipient) -> BasicExpertInfo:
    return BasicExpertInfo(display_name=recipient.name, email=recipient.address)


def _owners(
    messages: list[OutlookMessage],
) -> tuple[list[BasicExpertInfo], list[BasicExpertInfo]]:
    """Senders are primary owners, everyone else on the thread is secondary."""
    senders: dict[str, OutlookRecipient] = {}
    others: dict[str, OutlookRecipient] = {}
    for message in messages:
        if message.sender is not None:
            senders.setdefault(message.sender.address.lower(), message.sender)
        for recipient in message.to_recipients + message.cc_recipients:
            others.setdefault(recipient.address.lower(), recipient)
    for address in senders:
        others.pop(address, None)
    return (
        [_expert(r) for r in senders.values()],
        [_expert(r) for r in others.values()],
    )


T = TypeVar("T", bound=OutlookMessageIdentity)


def _conversation_pages(
    fetch: Callable[[str | None], tuple[list[T], str | None]],
    limit: int,
) -> Generator[list[T], None, None]:
    """A conversation's pages, newest first, until the next link runs out or
    ``limit`` raw messages have been read. The budget applies to raw messages,
    so a final page is cut to what is left of it."""
    fetched = 0
    next_link: str | None = None
    while fetched < limit:
        items, next_link = fetch(next_link)
        within_budget = items[: limit - fetched]
        fetched += len(within_budget)
        yield within_budget
        if next_link is None:
            return


def is_indexable(
    message: OutlookMessageIdentity, excluded_folder_ids: set[str]
) -> bool:
    """False for drafts and messages in excluded folders."""
    return not message.is_draft and message.parent_folder_id not in excluded_folder_ids


def indexable_messages(
    messages: list[OutlookMessage], excluded_folder_ids: set[str]
) -> list[OutlookMessage]:
    return [m for m in messages if is_indexable(m, excluded_folder_ids)]


def attachment_skip_reason(attachment: OutlookAttachment) -> str | None:
    """Why an attachment is not worth a download, None when it is."""
    if not attachment.is_file:
        return "not a file attachment"
    if attachment.is_inline:
        return "inline attachment"
    if (
        get_file_ext(attachment.name)
        not in OnyxFileExtensions.TEXT_AND_DOCUMENT_EXTENSIONS
    ):
        return "unsupported file type"
    if attachment.size > OUTLOOK_CONNECTOR_ATTACHMENT_SIZE_THRESHOLD:
        return "over the size threshold"
    return None


def _poll_bound(seconds: SecondsSinceUnixEpoch | None) -> datetime | None:
    """A poll window edge as a moment, None for an open edge."""
    return datetime.fromtimestamp(seconds, tz=timezone.utc) if seconds else None


def _occurrence_series_id(event: OutlookEvent) -> str | None:
    """The series an occurrence expands from, None for anything else. The one
    rule the series collapse hinges on."""
    if event.event_type == EVENT_OCCURRENCE and event.series_master_id:
        return event.series_master_id
    return None


def _user_access(emails: set[str]) -> ExternalAccess:
    return ExternalAccess(
        external_user_emails=emails, external_user_group_ids=set(), is_public=False
    )


def owner_access(mailbox: OutlookMailbox) -> ExternalAccess:
    """The mailbox's owner reads everything in it. A shared mailbox has no owner
    who signs in, so its folders stay hidden."""
    return _user_access({mailbox.address.lower()})


def readers_access(readers: Iterable[OutlookMailbox]) -> ExternalAccess:
    """Read access for the owners of the given mailboxes."""
    return _user_access({reader.address.lower() for reader in readers})


def slim_documents(
    plans: Iterable[DocumentPlan], include_permissions: bool
) -> list[SlimDocument]:
    """The ids indexing writes for a copy's plans, with their readers when
    permissions are wanted."""
    return [
        SlimDocument(
            id=plan.document_id,
            external_access=(
                readers_access(plan.readers) if include_permissions else None
            ),
        )
        for plan in plans
    ]


def event_access(mailbox: OutlookMailbox, event: OutlookEvent) -> ExternalAccess:
    """The owner plus the organizer and attendees, whom Outlook shows the
    meeting to as well."""
    emails = {mailbox.address.lower()}
    if event.organizer is not None:
        emails.add(event.organizer.address.lower())
    emails.update(attendee.address.lower() for attendee in event.attendees)
    return _user_access(emails)


def event_skip_reason(event: OutlookEvent) -> str | None:
    """Why an event is not indexed, None when it is."""
    if event.is_cancelled:
        return "cancelled"
    if event.sensitivity in SKIPPED_EVENT_SENSITIVITIES:
        return f"marked {event.sensitivity}"
    return None


def _scheduled_zone(name: str | None) -> ZoneInfo | None:
    """The zone Graph reports for an event, given as an IANA name or a Windows
    one, the latter through the CLDR mapping Babel ships. None for a name
    neither knows."""
    if not name:
        return None
    iana = get_global("windows_zone_mapping").get(name, name)
    try:
        return ZoneInfo(iana)
    except (ZoneInfoNotFoundError, ValueError):
        return None


def _format_event_time(event: OutlookEvent) -> str | None:
    if event.start_at is None:
        return None
    if event.is_all_day:
        # Graph gives an all-day event as midnight to midnight, converted to
        # UTC, so its dates are only right read back in the zone it was
        # scheduled in. It ends at midnight of the day after.
        zone = _scheduled_zone(event.time_zone) or timezone.utc
        first_day = event.start_at.astimezone(zone).date().isoformat()
        last_day = first_day
        if event.end_at is not None:
            last_day = (
                (event.end_at.astimezone(zone) - timedelta(days=1)).date().isoformat()
            )
        if last_day <= first_day:
            return f"{first_day} (all day)"
        return f"{first_day} to {last_day} (all day)"
    text = event.start_at.strftime("%Y-%m-%d %H:%M")
    if event.end_at is not None:
        same_day = event.end_at.date() == event.start_at.date()
        text += " to " + event.end_at.strftime(
            "%H:%M" if same_day else "%Y-%m-%d %H:%M"
        )
    text += " UTC"
    # The local hour of a series shifts against UTC with daylight saving, so
    # the zone it was scheduled in is the only fixed description of it.
    if event.time_zone and event.time_zone != "UTC":
        text += f" (scheduled in {event.time_zone})"
    return text


def build_event_document(
    mailbox: OutlookMailbox, event: OutlookEvent, include_permissions: bool = False
) -> Document:
    """One document per event: header lines, then the body, like a message."""
    lines: list[str] = []
    when = _format_event_time(event)
    if when is not None:
        lines.append(f"When: {when}")
    if event.recurrence:
        lines.append(f"Repeats: {event.recurrence}")
    if event.location:
        lines.append(f"Where: {event.location}")
    organizer = event.organizer
    if organizer is not None:
        lines.append(f"Organizer: {_format_recipient(organizer)}")
    if event.attendees:
        listed = ", ".join(
            _format_recipient(a) for a in event.attendees[:MAX_ATTENDEES_LISTED]
        )
        extra = len(event.attendees) - MAX_ATTENDEES_LISTED
        lines.append(
            f"Attendees: {listed}" + (f" and {extra} more" if extra > 0 else "")
        )
    if event.subject:
        lines.append(f"Subject: {event.subject}")
    text = "\n".join(lines) + "\n\n" + event.body_text

    others = {a.address.lower(): a for a in event.attendees}
    if organizer is not None:
        others.pop(organizer.address.lower(), None)
    subject = event.subject or "(no subject)"
    metadata: dict[str, str | list[str]] = {
        "mailbox": mailbox.address,
        "recurring": "true" if event.recurrence else "false",
    }
    if event.start_at is not None:
        metadata["start"] = event.start_at.isoformat()
    if event.end_at is not None:
        metadata["end"] = event.end_at.isoformat()
    if event.location:
        metadata["location"] = event.location
    return Document(
        id=event_document_id(mailbox, event.id),
        sections=[TextSection(link=event.web_link, text=text.strip())],
        source=DocumentSource.OUTLOOK,
        semantic_identifier=subject,
        title=subject,
        doc_created_at=event.created_at,
        doc_updated_at=event.last_modified_at or event.created_at,
        primary_owners=[_expert(organizer)] if organizer is not None else [],
        secondary_owners=[_expert(a) for a in others.values()],
        metadata=metadata,
        parent_hierarchy_raw_node_id=calendar_node_id(mailbox),
        external_access=event_access(mailbox, event) if include_permissions else None,
    )


@dataclass
class AttachmentBudget:
    """What one conversation may still spend on attachments: characters kept
    and download-plus-extraction attempts, successful or not."""

    text: int = MAX_ATTACHMENT_TEXT_PER_CONVERSATION
    reads: int = MAX_ATTACHMENT_READS_PER_CONVERSATION

    @property
    def spent(self) -> bool:
        return self.text <= 0 or self.reads <= 0


def extract_attachment_text(data: bytes, name: str, cap: int) -> str:
    """Runs in a child process: the in-process parsers only, since the
    Unstructured key lives in a database the child cannot reach, PDFium in
    this process so no grandchild outlives it, and the cap applied here so the
    parent never receives more text than it keeps."""
    text = extract_file_text_locally(BytesIO(data), name, isolate_pdfium=False)
    return text.strip()[:cap]


def build_thread_document(
    document_id: str,
    mailbox: OutlookMailbox,
    readers: list[OutlookMailbox],
    messages: list[OutlookMessage],
    attachment_sections: dict[str, list[TextSection]] | None = None,
    include_permissions: bool = False,
) -> Document | None:
    """Assemble the messages of one document, oldest first, each followed by
    the text of its attachments. None when there is nothing to index."""
    kept = sorted(messages, key=_message_sort_key)
    if not kept:
        return None

    attachments = attachment_sections or {}
    sections: list[TextSection] = []
    for message in kept:
        sections.append(_message_section(message))
        sections.extend(attachments.get(message.id, []))
    subject = next((m.subject for m in kept if m.subject), None) or "(no subject)"
    primary_owners, secondary_owners = _owners(kept)
    newest = kept[-1]
    return Document(
        id=document_id,
        sections=sections,
        source=DocumentSource.OUTLOOK,
        semantic_identifier=subject,
        title=subject,
        doc_created_at=_message_sort_key(kept[0]),
        doc_updated_at=_message_sort_key(newest),
        primary_owners=primary_owners,
        secondary_owners=secondary_owners,
        metadata={
            "mailbox": mailbox.address,
            "mailbox_count": str(len(readers)),
            "message_count": str(len(kept)),
        },
        parent_hierarchy_raw_node_id=newest.parent_folder_id
        or mailbox_node_id(mailbox),
        external_access=(readers_access(readers) if include_permissions else None),
    )


class OutlookConnector(
    CredentialsConnector,
    CheckpointedConnectorWithPermSync[OutlookCheckpoint],
    SlimConnector,
    SlimConnectorWithPermSync,
):
    def __init__(
        self,
        mailboxes: list[str] | None = None,
        mailbox_groups: list[str] | None = None,
        excluded_folders: list[str] | None = None,
        include_attachments: bool = False,
        include_calendar: bool = False,
        calendar_past_days: int = DEFAULT_CALENDAR_PAST_DAYS,
        calendar_future_days: int = DEFAULT_CALENDAR_FUTURE_DAYS,
        authority_host: str = DEFAULT_AUTHORITY_HOST,
        graph_api_host: str = DEFAULT_GRAPH_API_HOST,
        batch_size: int = INDEX_BATCH_SIZE,
    ) -> None:
        # Addresses, then Entra groups by display name or object id whose
        # members are walked. Both empty means every mailbox the app may open.
        self.mailboxes = clean_names(mailboxes)
        self.mailbox_groups = clean_names(mailbox_groups)
        self.include_attachments = include_attachments
        self.include_calendar = include_calendar
        if calendar_past_days < 0 or calendar_future_days < 0:
            raise ConnectorValidationError("Calendar window days cannot be negative.")
        self.calendar_past_days = calendar_past_days
        self.calendar_future_days = calendar_future_days
        self.excluded_folder_names = {
            name.strip().casefold() for name in excluded_folders or [] if name.strip()
        }
        self.authority_host = authority_host.rstrip("/")
        self.graph_api_host = graph_api_host.rstrip("/")
        resolve_microsoft_environment(self.graph_api_host, self.authority_host)
        self.batch_size = batch_size
        self._ops: OutlookSourceOperations | None = None
        # The listings of the mailboxes in flight, by mailbox id.
        self._listings: dict[str, _MailboxListing] = {}
        # Whether each probed mailbox can be opened, so a thread's builder is
        # one that will build. Filled as mailboxes open and as builders are
        # probed, once per mailbox per process.
        self._available: dict[str, bool] = {}
        # The run's mailboxes by address, resolved again by a resuming process.
        self._roster: Roster | None = None

    @property
    def ops(self) -> OutlookSourceOperations:
        if self._ops is None:
            raise ConnectorMissingCredentialError("Outlook")
        return self._ops

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self.set_credentials_provider(
            OnyxStaticCredentialsProvider(
                None, DocumentSource.OUTLOOK.value, credentials
            )
        )
        return None

    def set_credentials_provider(
        self, credentials_provider: CredentialsProviderInterface
    ) -> None:
        self._ops = OutlookSourceOperations(
            credentials_provider=credentials_provider,
            connector_specific_config={
                CONFIG_AUTHORITY_HOST: self.authority_host,
                CONFIG_GRAPH_API_HOST: self.graph_api_host,
            },
        )

    def validate_connector_settings(self) -> None:
        try:
            self.ops.check_token()
        except OutlookAuthError as e:
            raise_for_auth_error(e)
        except OutlookGraphError as e:
            raise_for_graph_error(e, "Microsoft's token endpoint refused the request.")

        if not self.mailboxes and not self.mailbox_groups:
            try:
                self.ops.list_mailbox_users(page_size=1)
            except OutlookGraphError as e:
                raise_for_graph_error(
                    e, "The app cannot list the tenant's users for every-mailbox mode."
                )
            return
        raise_if_unavailable(describe_unavailable_mailboxes(self.ops, self.mailboxes))
        raise_if_groups_unavailable(
            describe_unavailable_groups(self.ops, self.mailbox_groups)
        )

    def build_dummy_checkpoint(self) -> OutlookCheckpoint:
        return OutlookCheckpoint(has_more=True)

    def validate_checkpoint_json(self, checkpoint_json: str) -> OutlookCheckpoint:
        return OutlookCheckpoint.model_validate_json(checkpoint_json)

    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: OutlookCheckpoint,
    ) -> CheckpointOutput[OutlookCheckpoint]:
        """One unit of work per call: enumerate the mailboxes, or advance each
        active mailbox (open it, list one delta page, build a few of its
        conversations, or read one calendar page). The checkpoint records
        where to resume."""
        return self._load_from_checkpoint(
            start, end, checkpoint, include_permissions=False
        )

    def load_from_checkpoint_with_perm_sync(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: OutlookCheckpoint,
    ) -> CheckpointOutput[OutlookCheckpoint]:
        """The same walk with each document's readers attached, so a connector
        set to Auto Sync Permissions is searchable from its first index."""
        return self._load_from_checkpoint(
            start, end, checkpoint, include_permissions=True
        )

    def _load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: OutlookCheckpoint,
        include_permissions: bool,
    ) -> CheckpointOutput[OutlookCheckpoint]:
        try:
            return (yield from self._step(checkpoint, start, end, include_permissions))
        except OutlookGraphError as e:
            if e.status != THROTTLED_STATUS:
                raise
            # The client already backed off and retried. The attempt's error
            # is what the admin reads, so say what happened in plain words.
            raise RateLimitTriedTooManyTimesError(THROTTLED_MESSAGE) from e

    def _step(
        self,
        checkpoint: OutlookCheckpoint,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        include_permissions: bool,
    ) -> CheckpointOutput[OutlookCheckpoint]:
        if checkpoint.mailboxes is None:
            yield from self._enumerate_mailboxes(checkpoint)
            return checkpoint
        if checkpoint.mailboxes or checkpoint.active:
            yield from self._listing_step(checkpoint, start, end, include_permissions)
            return checkpoint
        checkpoint.has_more = False
        return checkpoint

    def _listing_step(
        self,
        checkpoint: OutlookCheckpoint,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        include_permissions: bool,
    ) -> Generator[HierarchyNode | Document | ConnectorFailure, None, None]:
        """One unit of work in each active mailbox, side by side.

        Worked on copies and written back only once every mailbox finished
        its unit, so a raise in one leaves the whole step to be retried.
        """
        queued: list[OutlookMailbox] = list(checkpoint.mailboxes or [])
        cursors: list[MailboxCursor] = [
            self._resumable(cursor.model_copy(deep=True))
            for cursor in checkpoint.active
        ]
        while len(cursors) < MAILBOX_WORKERS and queued:
            cursors.append(MailboxCursor(mailbox=queued.pop()))
        roster: Roster = self._run_roster()
        results: list[MailboxStep] = run_functions_tuples_in_parallel(
            [
                (
                    self._advance_mailbox,
                    (cursor, roster, start, end, include_permissions),
                )
                for cursor in cursors
            ],
            max_workers=MAILBOX_WORKERS,
        )
        for cursor, result in zip(cursors, results, strict=True):
            listing = self._listings.setdefault(cursor.mailbox.id, _MailboxListing())
            listing.rows.extend(result.rows)
            yield from result.items
            if len(listing.rows) > MAX_LISTING_ROWS_PER_MAILBOX:
                yield _oversized_mailbox_failure(cursor.mailbox)
                cursor.finished = True
                continue
            if cursor.listed and not listing.grouped:
                listing.group()
                cursor.to_build = len(listing.conversations)
        for cursor in cursors:
            if cursor.finished:
                self._listings.pop(cursor.mailbox.id, None)
        checkpoint.mailboxes = queued
        checkpoint.active = [cursor for cursor in cursors if not cursor.finished]

    def _resumable(self, cursor: MailboxCursor) -> MailboxCursor:
        """The cursor as this process can continue it. A mailbox part way
        through its listing or its build in another process is walked again
        from the start, since its listing lived there."""
        needs_listing = cursor.opened and not (
            cursor.listed and cursor.built >= cursor.to_build
        )
        if not needs_listing or cursor.mailbox.id in self._listings:
            return cursor
        logger.info(
            "Outlook: walking %s again from the start, its listing is not in "
            "this process",
            cursor.mailbox.address,
        )
        return MailboxCursor(mailbox=cursor.mailbox)

    def _mailbox_available(self, mailbox: OutlookMailbox) -> bool:
        """Whether the run can open the mailbox, probed once per process. A
        refusal is permanent for the run; anything else raises, since
        guessing would hand the thread to a builder that never builds."""
        known: bool | None = self._available.get(mailbox.id)
        if known is not None:
            return known
        try:
            self.ops.probe_mailbox(mailbox_id=mailbox.id)
        except OutlookGraphError as e:
            if not e.is_permanent_refusal:
                raise
            logger.info(
                "Outlook: %s cannot be opened (%s), it builds no thread",
                mailbox.address,
                e.code,
            )
            self._available[mailbox.id] = False
            return False
        self._available[mailbox.id] = True
        return True

    def _run_roster(self) -> Roster:
        """The run's mailboxes by address. Resolved when the run starts and
        again by a process that resumes it."""
        if self._roster is None:
            mailboxes, _ = self._resolve_mailboxes()
            self._roster = roster_of(mailboxes)
        return self._roster

    def _build_step(
        self,
        cursor: MailboxCursor,
        start: SecondsSinceUnixEpoch,
        include_permissions: bool,
    ) -> list[Document | ConnectorFailure]:
        """Builds the next CONVERSATIONS_PER_STEP conversations of the
        mailbox's listing, side by side."""
        conversations = self._listings[cursor.mailbox.id].conversations
        batch = conversations[cursor.built : cursor.built + CONVERSATIONS_PER_STEP]
        excluded = set(cursor.excluded_folder_ids)
        results: list[list[Document | ConnectorFailure]] = (
            run_functions_tuples_in_parallel(
                [
                    (
                        self._build_conversation,
                        (
                            cursor.mailbox,
                            excluded,
                            rows,
                            self._listed_from_the_beginning(start),
                            include_permissions,
                        ),
                    )
                    for rows in batch
                ],
                max_workers=CONVERSATION_BUILD_WORKERS,
            )
        )
        cursor.built += len(batch)
        return [item for items in results for item in items]

    def _listed_from_the_beginning(self, start: SecondsSinceUnixEpoch) -> bool:
        """True when the listing window has no lower bound, so the listing
        holds every indexable message of each copy and no outline needs to be
        read."""
        return _poll_bound(start) is None

    def _advance_mailbox(
        self,
        cursor: MailboxCursor,
        roster: Roster,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        include_permissions: bool,
    ) -> MailboxStep:
        """One unit of work in one mailbox: open it, list one delta page,
        build a few conversations, or read one calendar page."""
        if not cursor.opened:
            return MailboxStep(
                items=list(self._open_mailbox(cursor, include_permissions))
            )
        if not cursor.listed:
            if cursor.current_folder is None:
                if not cursor.folders:
                    cursor.listed = True
                    return MailboxStep()
                cursor.current_folder = cursor.folders.pop()
                self._reset_folder_cursor(cursor)
            return self._read_folder_page(cursor, roster, start, end)
        if cursor.built < cursor.to_build:
            return MailboxStep(
                items=self._build_step(cursor, start, include_permissions)
            )
        if self.include_calendar and not cursor.calendar_done:
            return MailboxStep(
                items=list(self._read_calendar_page(cursor, start, include_permissions))
            )
        cursor.finished = True
        return MailboxStep()

    def _reset_folder_cursor(self, cursor: MailboxCursor) -> None:
        cursor.delta_next_link = None
        cursor.folder_change_count = 0
        cursor.folder_unfiltered = False

    def _unavailable(
        self, entity_id: str, message: str, error: OutlookGraphError
    ) -> Generator[ConnectorFailure, None, None]:
        """Something Graph refuses is a recorded failure when the admin named
        its mailbox and a log line in every-mailbox mode."""
        if self.mailboxes:
            yield _mailbox_failure(entity_id, message, error)
            return
        logger.info("Outlook: skipping %s, unavailable (%s)", entity_id, error.code)

    def _mailbox_unavailable(
        self, mailbox: OutlookMailbox, error: OutlookGraphError
    ) -> Generator[ConnectorFailure, None, None]:
        """Unlicensed, locked, or out of the app's Exchange scope."""
        yield from self._unavailable(
            mailbox.address,
            f"Mailbox {mailbox.address} is unavailable ({error.code}). "
            f"{EXCHANGE_SCOPE_REMEDIATION}",
            error,
        )

    def _calendar_unavailable(
        self, mailbox: OutlookMailbox, error: OutlookGraphError
    ) -> Generator[ConnectorFailure, None, None]:
        """No calendar grant, none for this mailbox, or locked. Its mail stays
        indexed."""
        yield from self._unavailable(
            f"{mailbox.address} calendar",
            f"Calendar of {mailbox.address} is unavailable ({error.code}). "
            f"{CALENDAR_READ_REMEDIATION}",
            error,
        )

    def _resolve_mailboxes(
        self,
    ) -> tuple[list[OutlookMailbox], list[ConnectorFailure]]:
        """The mailboxes to walk: the configured addresses, then the members
        of the configured groups, or every mailbox when neither is set. Comes
        with a failure per configured address or group that cannot be resolved."""
        found: list[OutlookMailbox] = []
        failures: list[ConnectorFailure] = []
        # Resolution reads the directory, never a mailbox, so a Graph error
        # here is about the app or the service and fails the attempt instead
        # of dropping the address or the group.
        for address in self.mailboxes:
            mailbox = self.ops.resolve_mailbox(address=address)
            if mailbox is None:
                failures.append(
                    _mailbox_failure(
                        address,
                        f"No user matches {address}. {MAILBOX_UNAVAILABLE_REMEDIATION}",
                    )
                )
                continue
            found.append(mailbox)
        for identifier in self.mailbox_groups:
            groups: list[EntraGroup] = self.ops.resolve_groups(identifier=identifier)
            if len(groups) != 1:
                failures.append(
                    _mailbox_failure(
                        identifier,
                        f"{describe_group_mismatch(identifier, len(groups))}. "
                        f"{GROUP_UNAVAILABLE_REMEDIATION}",
                    )
                )
                continue
            found.extend(self._group_mailboxes(groups[0].id))
        if not self.mailboxes and not self.mailbox_groups:
            found.extend(
                self._listed_mailboxes(
                    lambda next_link: self.ops.list_mailbox_users(next_link=next_link)
                )
            )
        # A UPN and a primary SMTP address, or two listing pages, can name the
        # same mailbox. The dict keeps the first occurrence in order.
        unique = list({mailbox.id: mailbox for mailbox in found}.values())
        logger.info("Outlook: %s mailboxes to walk", len(unique))
        return unique, failures

    def _listed_mailboxes(
        self, fetch_page: Callable[[str | None], OutlookMailboxPage]
    ) -> list[OutlookMailbox]:
        """Every mailbox of a paged mailbox listing."""
        # TODO(nmgarza5): list across checkpoint steps and carry compact
        # mailbox records, so a huge tenant survives a failure mid-listing.
        mailboxes: list[OutlookMailbox] = []
        next_link: str | None = None
        for _ in range(MAX_MAILBOX_LISTING_PAGES):
            page = fetch_page(next_link)
            mailboxes.extend(page.mailboxes)
            next_link = page.next_link
            if next_link is None:
                return mailboxes
        raise RuntimeError(
            "Outlook: the mailbox listing ran past "
            f"{MAX_MAILBOX_LISTING_PAGES} pages without ending"
        )

    def _group_mailboxes(self, group_id: str) -> list[OutlookMailbox]:
        # Bound per group here, since a lambda in the loop above late-binds.
        return self._listed_mailboxes(
            lambda next_link: self.ops.list_group_mailbox_users(
                group_id=group_id, next_link=next_link
            )
        )

    def _enumerate_mailboxes(
        self, checkpoint: OutlookCheckpoint
    ) -> Generator[ConnectorFailure, None, None]:
        mailboxes, failures = self._resolve_mailboxes()
        self._roster = roster_of(mailboxes)
        # Popped from the end, so reverse to keep the configured order.
        checkpoint.mailboxes = list(reversed(mailboxes))
        # Yielded once the checkpoint is complete, so a lookup that raises
        # part way does not repeat them on the retry.
        yield from failures

    def retrieve_all_slim_docs(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        """Every thread and event document id the walk would produce today,
        so pruning drops the ones that vanished.

        Reads folder and delta metadata only, never a body. A mailbox whose
        probe answers 404 is gone and contributes nothing, so its documents go
        too. Any other Graph failure raises: an aborted prune deletes nothing,
        while a silent skip would delete every document of that mailbox.
        """
        del start, end
        yield from self._slim_docs(callback, include_permissions=False)

    def retrieve_all_slim_docs_perm_sync(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        """The pruning walk with each document's readers attached: the owner
        on every node, every holder on a thread, and the owner plus the
        organizer and attendees on an event."""
        del start, end
        yield from self._slim_docs(callback, include_permissions=True)

    def _slim_docs(
        self, callback: IndexingHeartbeatInterface | None, include_permissions: bool
    ) -> GenerateSlimDocumentOutput:
        mailboxes, failures = self._resolve_mailboxes()
        # An address or a group that cannot be resolved is a configuration
        # problem, not a verdict on the mailboxes behind it, so the walk stops
        # here rather than list those mailboxes as empty.
        if failures:
            names = ", ".join(
                failure.failed_entity.entity_id
                for failure in failures
                if failure.failed_entity is not None
            )
            raise ConnectorValidationError(
                f"These mailboxes or groups cannot be resolved: {names}. Fix or "
                "remove them from the connector before pruning or permission sync."
            )
        self._roster = roster_of(mailboxes)
        # Each worker drains the shared queue one mailbox at a time, so the
        # walk's threads stay busy until it is empty. The heartbeat and the
        # yields live on this thread.
        queue: deque[OutlookMailbox] = deque(mailboxes)
        workers: list[Iterator[list[SlimDocument | HierarchyNode]]] = [
            self._slim_worker_pages(queue, include_permissions)
            for _ in range(min(MAILBOX_WORKERS, len(mailboxes)))
        ]
        yield from self._slim_batches(
            parallel_yield(workers, max_workers=MAILBOX_WORKERS), callback
        )

    def _slim_worker_pages(
        self, queue: deque[OutlookMailbox], include_permissions: bool
    ) -> Generator[list[SlimDocument | HierarchyNode], None, None]:
        while queue:
            try:
                mailbox = queue.popleft()
            except IndexError:
                return
            yield from self._slim_mailbox_pages(mailbox, include_permissions)

    def _slim_mailbox_pages(
        self, mailbox: OutlookMailbox, include_permissions: bool
    ) -> Generator[list[SlimDocument | HierarchyNode], None, None]:
        """One mailbox's part of the slim walk: its folder nodes, an empty
        page per delta page read so the caller's heartbeat keeps up, its
        thread documents once every folder is listed, then its events.
        Nothing for a mailbox that is gone."""
        try:
            self.ops.probe_mailbox(mailbox_id=mailbox.id)
            self._available[mailbox.id] = True
        except OutlookGraphError as e:
            # Past the probe a 404 is a vanished folder, which aborts the walk.
            if e.status == 404:
                self._available[mailbox.id] = False
                logger.info(
                    "Outlook: %s is gone, listing nothing for it", mailbox.address
                )
                return
            raise
        excluded = self._excluded_well_known_folder_ids(mailbox)
        tree = list(self._walk_folder_tree(mailbox, excluded))
        access = owner_access(mailbox) if include_permissions else None
        yield list(self._hierarchy_nodes(mailbox, tree, access))
        # A copy's documents are decided across its folders, so the mailbox's
        # listing is held whole. One mailbox per worker at a time.
        listing = _MailboxListing()
        for rows in self._thread_listing_pages(mailbox, tree):
            listing.rows.extend(rows)
            if len(listing.rows) > MAX_LISTING_ROWS_PER_MAILBOX:
                # Listing nothing for it would prune its documents.
                raise ConnectorValidationError(_oversized_mailbox_message(mailbox))
            yield []
        listing.group()
        documents: list[SlimDocument | HierarchyNode] = []
        for rows in listing.conversations or []:
            documents.extend(
                slim_documents(
                    plan_documents(rows, mailbox, self._mailbox_available),
                    include_permissions,
                )
            )
            if len(documents) >= SLIM_BATCH_SIZE:
                yield documents
                documents = []
        if documents:
            yield documents
        if self.include_calendar:
            for events in self._event_slim_pages(mailbox, include_permissions):
                yield [*events]

    def _slim_batches(
        self,
        pages: Iterable[list[SlimDocument | HierarchyNode]],
        callback: IndexingHeartbeatInterface | None,
    ) -> GenerateSlimDocumentOutput:
        """Documents batched across pages, each page reported to the heartbeat."""
        batch: list[SlimDocument | HierarchyNode] = []
        for docs in pages:
            batch.extend(docs)
            while len(batch) >= SLIM_BATCH_SIZE:
                yield batch[:SLIM_BATCH_SIZE]
                batch = batch[SLIM_BATCH_SIZE:]
            if callback is not None:
                callback.progress("outlook_slim_docs", len(docs))
        if batch:
            yield batch

    def _thread_listing_pages(
        self, mailbox: OutlookMailbox, tree: list[tuple[OutlookFolder, str]]
    ) -> Generator[list[ThreadListing], None, None]:
        """The messages of every folder in the tree, one list per delta page.
        Any Graph error raises, since pruning and permission sync must both
        see the whole mailbox or nothing."""
        roster: Roster = self._run_roster()
        for folder, _ in tree:
            next_link: str | None = None
            while True:
                # A 410 mid-round is not restarted here: ids already yielded
                # from the expired round cannot be retracted, so the walk
                # aborts and runs again later.
                page = self.ops.fetch_folder_delta_page(
                    mailbox_id=mailbox.id, folder_id=folder.id, next_link=next_link
                )
                yield [
                    row
                    for change in page.changes
                    if (row := listing_row(change, roster)) is not None
                ]
                next_link = page.next_link
                if next_link is None:
                    break

    def _event_slim_pages(
        self, mailbox: OutlookMailbox, include_permissions: bool
    ) -> Generator[list[SlimDocument], None, None]:
        """Event documents of the calendar window, admitted by the rule
        indexing applies: skips on the row, and a series only when its master
        is readable and not excluded, read once per series per mailbox. Ids
        are deduplicated per page only, since a repeat costs the callers
        nothing. With permissions, a series carries the readers of its master,
        the event indexing writes it from.

        A calendar that is gone (404 on the first page) lists nothing, so its
        events are pruned like the mail of a vanished mailbox. A refused one
        (403) aborts the walk with the grant to fix: listing nothing would
        prune its events, and the poll window skips unchanged events, so they
        would return only with a full re-index. An error later in the round
        raises, since the ids already listed cannot be retracted.
        """
        window_start, window_end = self._calendar_window()
        series_readers: dict[str, ExternalAccess | None] = {}
        next_link: str | None = None
        while True:
            try:
                page = self.ops.fetch_calendar_delta_page(
                    mailbox_id=mailbox.id,
                    window_start=window_start,
                    window_end=window_end,
                    next_link=next_link,
                )
            except OutlookGraphError as e:
                if e.status == 404 and next_link is None:
                    logger.info(
                        "Outlook: calendar of %s is gone, listing no events for it",
                        mailbox.address,
                    )
                    return
                if e.status == 403 and next_link is None:
                    raise ConnectorValidationError(
                        f"The calendar of {mailbox.address} is refused ({e.code}), "
                        "so its mailbox cannot be listed for pruning or permission "
                        f"sync. {CALENDAR_READ_REMEDIATION} Or turn Include "
                        "Calendar off."
                    ) from e
                raise
            docs: dict[str, SlimDocument] = {}
            for event in page.events:
                if event_skip_reason(event) is not None:
                    continue
                series_id = _occurrence_series_id(event)
                event_id = series_id or event.id
                if event_id in docs:
                    continue
                readers = event_access(mailbox, event)
                if series_id is not None:
                    master_readers = self._listed_series_readers(
                        mailbox, series_id, series_readers
                    )
                    if master_readers is None:
                        continue
                    readers = master_readers
                docs[event_id] = SlimDocument(
                    id=event_document_id(mailbox, event_id),
                    external_access=readers if include_permissions else None,
                )
            yield list(docs.values())
            next_link = page.next_link
            if next_link is None:
                break

    def _listed_series_readers(
        self,
        mailbox: OutlookMailbox,
        series_id: str,
        decided: dict[str, ExternalAccess | None],
    ) -> ExternalAccess | None:
        """The readers of a listed series, taken from the master indexing writes
        it from, or None when the series is excluded. Decided once per mailbox
        and remembered in ``decided``, capped like the checkpoint's set so a
        huge calendar costs repeat master reads rather than memory."""
        if series_id in decided:
            return decided[series_id]
        master = self._indexable_series_master(mailbox, series_id)
        readers = event_access(mailbox, master) if master is not None else None
        if len(decided) < MAX_TRACKED_SERIES_PER_MAILBOX:
            decided[series_id] = readers
        return readers

    def _open_mailbox(
        self, cursor: MailboxCursor, include_permissions: bool
    ) -> Generator[HierarchyNode | ConnectorFailure, None, None]:
        """Probe the mailbox, then list its whole folder tree.

        Nothing is yielded until the tree is known, so a listing that fails
        part way leaves nothing behind for the retry to repeat.
        """
        mailbox = cursor.mailbox
        try:
            self.ops.probe_mailbox(mailbox_id=mailbox.id)
            self._available[mailbox.id] = True
            excluded = self._excluded_well_known_folder_ids(mailbox)
            tree = list(self._walk_folder_tree(mailbox, excluded))
        except OutlookGraphError as e:
            if not e.is_permanent_refusal:
                raise
            self._available[mailbox.id] = False
            yield from self._mailbox_unavailable(mailbox, e)
            cursor.finished = True
            return

        access = owner_access(mailbox) if include_permissions else None
        yield from self._hierarchy_nodes(mailbox, tree, access)

        cursor.opened = True
        cursor.folders = list(reversed([folder for folder, _ in tree]))
        cursor.excluded_folder_ids = sorted(excluded)

    def _hierarchy_nodes(
        self,
        mailbox: OutlookMailbox,
        tree: list[tuple[OutlookFolder, str]],
        access: ExternalAccess | None = None,
    ) -> Generator[HierarchyNode, None, None]:
        yield HierarchyNode(
            raw_node_id=mailbox_node_id(mailbox),
            raw_parent_id=None,
            display_name=mailbox.display_name or mailbox.address,
            link=_mailbox_link(mailbox),
            node_type=HierarchyNodeType.MAILBOX,
            external_access=access,
        )
        for folder, parent_node_id in tree:
            yield HierarchyNode(
                raw_node_id=folder.id,
                raw_parent_id=parent_node_id,
                display_name=folder.display_name,
                node_type=HierarchyNodeType.FOLDER,
                external_access=access,
            )
        if self.include_calendar:
            yield HierarchyNode(
                raw_node_id=calendar_node_id(mailbox),
                raw_parent_id=mailbox_node_id(mailbox),
                display_name="Calendar",
                link=_calendar_link(mailbox),
                node_type=HierarchyNodeType.FOLDER,
                external_access=access,
            )

    def _excluded_well_known_folder_ids(self, mailbox: OutlookMailbox) -> set[str]:
        excluded: set[str] = set()
        for name in DEFAULT_EXCLUDED_WELL_KNOWN_FOLDERS:
            folder = self.ops.get_well_known_folder(mailbox_id=mailbox.id, name=name)
            if folder is not None:
                excluded.add(folder.id)
        return excluded

    def _walk_folder_tree(
        self, mailbox: OutlookMailbox, excluded: set[str]
    ) -> Generator[tuple[OutlookFolder, str], None, None]:
        """Yield every indexable folder with its hierarchy parent id, breadth
        first. Excluded subtrees are still descended so ``excluded`` ends up
        holding every folder id a conversation message could sit in."""
        root_id = mailbox_node_id(mailbox)
        # (parent folder id or None for the root, hierarchy parent raw id, excluded)
        queue: deque[tuple[str | None, str, bool]] = deque([(None, root_id, False)])
        while queue:
            parent_folder_id, parent_node_id, parent_excluded = queue.popleft()
            next_link: str | None = None
            while True:
                page = self.ops.list_child_folders(
                    mailbox_id=mailbox.id,
                    parent_folder_id=parent_folder_id,
                    next_link=next_link,
                )
                for folder in page.folders:
                    if folder.is_search_folder:
                        continue
                    is_excluded = (
                        parent_excluded
                        or folder.is_hidden
                        or folder.id in excluded
                        or folder.display_name.casefold() in self.excluded_folder_names
                    )
                    if is_excluded:
                        excluded.add(folder.id)
                    else:
                        yield folder, parent_node_id
                    if folder.child_folder_count > 0:
                        queue.append((folder.id, folder.id, is_excluded))
                next_link = page.next_link
                if next_link is None:
                    break

    def _read_folder_page(
        self,
        cursor: MailboxCursor,
        roster: Roster,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
    ) -> MailboxStep:
        mailbox = cursor.mailbox
        folder = cursor.current_folder
        if folder is None:
            raise ValueError("Cannot read a folder page without a current folder")

        window_start = _poll_bound(start)
        try:
            page = self.ops.fetch_folder_delta_page(
                mailbox_id=mailbox.id,
                folder_id=folder.id,
                received_after=None if cursor.folder_unfiltered else window_start,
                next_link=cursor.delta_next_link,
            )
        except OutlookGraphError as e:
            # Graph drops delta state with 410. Start the folder's round over.
            if e.status == 410 and cursor.delta_next_link is not None:
                cursor.delta_next_link = None
                cursor.folder_change_count = 0
                return MailboxStep()
            # The folder disappeared mid-run. Nothing left to index in it.
            if e.status == 404:
                logger.info(
                    "Outlook: folder %s in %s vanished, skipping",
                    folder.display_name,
                    mailbox.address,
                )
                cursor.current_folder = None
                return MailboxStep()
            # Access to the whole mailbox is gone, so stop walking it rather
            # than record one failure per remaining folder.
            if e.status == 403:
                cursor.finished = True
                return MailboxStep(items=list(self._mailbox_unavailable(mailbox, e)))
            raise

        end_at = _poll_bound(end)
        # Keyed by message so a copy the page lists twice is recorded once.
        rows: dict[str, ThreadListing] = {}
        for change in page.changes:
            # Read-state entries arrive for old messages whatever the filter
            # says, so the window is applied again here.
            if (
                window_start
                and change.received_at
                and change.received_at < window_start
            ):
                continue
            if end_at and change.received_at and change.received_at > end_at:
                continue
            row = listing_row(change, roster)
            if row is not None:
                rows.setdefault(row.message_id, row)

        # Committed with the cursor, so a page replayed after a failure part
        # way through is counted once.
        cursor.folder_change_count += len(page.changes)
        cursor.delta_next_link = page.next_link
        if page.next_link is not None:
            return MailboxStep(rows=list(rows.values()))
        filled_cap = (
            window_start is not None
            and not cursor.folder_unfiltered
            and cursor.folder_change_count >= FILTERED_DELTA_CAP
        )
        if filled_cap:
            logger.info(
                "Outlook: folder %s in %s filled the filtered delta cap, "
                "re-reading it without the filter",
                folder.display_name,
                mailbox.address,
            )
            self._reset_folder_cursor(cursor)
            cursor.folder_unfiltered = True
            return MailboxStep(rows=list(rows.values()))
        cursor.current_folder = None
        return MailboxStep(rows=list(rows.values()))

    def _calendar_window(self) -> tuple[datetime, datetime]:
        """The event times the calendar view covers, around the moment of the call."""
        now = datetime.now(timezone.utc)
        return (
            now - timedelta(days=self.calendar_past_days),
            now + timedelta(days=self.calendar_future_days),
        )

    def _read_calendar_page(
        self,
        cursor: MailboxCursor,
        start: SecondsSinceUnixEpoch,
        include_permissions: bool,
    ) -> Generator[Document | ConnectorFailure, None, None]:
        mailbox = cursor.mailbox

        window_start, window_end = self._calendar_window()
        try:
            page = self.ops.fetch_calendar_delta_page(
                mailbox_id=mailbox.id,
                window_start=window_start,
                window_end=window_end,
                next_link=cursor.calendar_next_link,
            )
        except OutlookGraphError as e:
            # Graph drops delta state with 410. Start the round over.
            if e.status == 410 and cursor.calendar_next_link is not None:
                cursor.calendar_next_link = None
                return
            if e.is_permanent_refusal:
                yield from self._calendar_unavailable(mailbox, e)
                cursor.calendar_done = True
                return
            raise

        modified_after = _poll_bound(start)
        for event in page.events:
            document = self._event_document(
                mailbox,
                event,
                modified_after,
                cursor.seen_series_ids,
                include_permissions,
            )
            if document is not None:
                yield document
        cursor.calendar_next_link = page.next_link
        cursor.calendar_done = page.next_link is None

    def _event_document(
        self,
        mailbox: OutlookMailbox,
        event: OutlookEvent,
        modified_after: datetime | None,
        seen_series_ids: set[str],
        include_permissions: bool,
    ) -> Document | None:
        """The document for one calendar view row, or None when the row adds
        nothing: unchanged since the poll window opened, skipped, or one more
        occurrence of a series already resolved this attempt."""
        if not self._changed_since(event, modified_after):
            return None
        reason = event_skip_reason(event)
        if reason is not None:
            logger.debug("Outlook: skipping event %s, %s", event.id, reason)
            return None
        series_id = _occurrence_series_id(event)
        if series_id is not None:
            if series_id in seen_series_ids:
                return None
            master = self._indexable_series_master(mailbox, series_id)
            if len(seen_series_ids) < MAX_TRACKED_SERIES_PER_MAILBOX:
                seen_series_ids.add(series_id)
            if master is None:
                return None
            event = master
        return build_event_document(mailbox, event, include_permissions)

    def _indexable_series_master(
        self, mailbox: OutlookMailbox, series_id: str
    ) -> OutlookEvent | None:
        """The master of a series when it is readable and not excluded, None
        otherwise. Indexing writes a series from it and pruning lists a series
        by it, so both admit a series by the same rule. Occurrence rows mirror
        their master, but the master's text is what gets indexed, so it is
        checked in its own right."""
        master = self._series_master(mailbox, series_id)
        if master is None or event_skip_reason(master) is not None:
            return None
        return master

    def _changed_since(
        self, event: OutlookEvent, modified_after: datetime | None
    ) -> bool:
        """Whether the poll window admits the event. The view takes no filter,
        so it is applied here to the event's modification time, and an untouched
        event that has just entered the front of the window is admitted by its
        start time, since no earlier poll could have seen it. A window widened by
        a config edit admits nothing on its own: those events are unchanged and
        below the bar, so they wait for a re-index, which the form says."""
        if modified_after is None or event.last_modified_at is None:
            return True
        if event.last_modified_at >= modified_after:
            return True
        window_front = modified_after + timedelta(days=self.calendar_future_days)
        return event.start_at is not None and event.start_at >= window_front

    def _series_master(
        self, mailbox: OutlookMailbox, series_master_id: str
    ) -> OutlookEvent | None:
        """The master an occurrence expands from, so a series is one document
        instead of one per meeting in the window. None when Graph refuses it."""
        try:
            return self.ops.get_event(mailbox_id=mailbox.id, event_id=series_master_id)
        except OutlookGraphError as e:
            if e.fails_the_attempt:
                raise
            logger.warning(
                "Outlook: series master %s in %s unreadable (%s), skipping",
                series_master_id,
                mailbox.address,
                e.code,
            )
            return None

    def _build_conversation(
        self,
        mailbox: OutlookMailbox,
        excluded_folder_ids: set[str],
        rows: list[ThreadListing],
        listing_complete: bool,
        include_permissions: bool,
    ) -> list[Document | ConnectorFailure]:
        """The documents one conversation of the mailbox yields, by the rules
        in ``threads.py``. A poll lists only the messages of the window, so
        the copy is read whole through its outline first."""
        conversation_id: str = rows[0].conversation_id
        try:
            if not listing_complete:
                rows = self._conversation_outline(
                    mailbox, conversation_id, excluded_folder_ids
                )
            plans: list[DocumentPlan] = plan_documents(
                rows, mailbox, self._mailbox_available
            )
            if not plans:
                return []
            wanted: set[str] = {
                message_id for plan in plans for message_id in plan.message_ids
            }
            messages: list[OutlookMessage] = self._copy_messages(
                mailbox, conversation_id, excluded_folder_ids, wanted
            )
            attachments = self._conversation_attachments(mailbox, messages)
            by_id: dict[str, OutlookMessage] = {m.match_id: m for m in messages}
            documents: list[Document | ConnectorFailure] = []
            for plan in plans:
                document = build_thread_document(
                    plan.document_id,
                    mailbox,
                    plan.readers,
                    [by_id[m] for m in plan.message_ids if m in by_id],
                    attachments,
                    include_permissions,
                )
                if document is not None:
                    documents.append(document)
            return documents
        except OutlookGraphError as e:
            # A recorded failure lets the poll window move past the mail, so a
            # transient failure raises and keeps the checkpoint for the retry.
            if e.fails_the_attempt:
                raise
            # The copy, not the thread document: another mailbox may own that.
            return [
                ConnectorFailure(
                    failed_entity=EntityFailure(
                        entity_id=f"{mailbox.address}:{conversation_id}"
                    ),
                    failure_message=(
                        f"Failed to read conversation {conversation_id} in "
                        f"{mailbox.address}: {e}"
                    ),
                    exception=e,
                )
            ]

    def _conversation_outline(
        self,
        mailbox: OutlookMailbox,
        conversation_id: str,
        excluded_folder_ids: set[str],
    ) -> list[ThreadListing]:
        """The copy's newest CONVERSATION_FETCH_LIMIT indexable messages as
        listing rows, no bodies. The outline reads newest first, so a copy
        longer than that is asked for its oldest message as well: the first
        message chooses the builder, and a full listing would have it."""
        roster: Roster = self._run_roster()

        def fetch(
            next_link: str | None,
        ) -> tuple[list[OutlookMessageChange], str | None]:
            page = self.ops.fetch_conversation_outline_page(
                mailbox_id=mailbox.id,
                conversation_id=conversation_id,
                next_link=next_link,
            )
            return page.changes, page.next_link

        rows: list[ThreadListing] = []
        for changes in _conversation_pages(fetch, COMPARED_FETCH_LIMIT):
            for change in changes:
                if not is_indexable(change, excluded_folder_ids):
                    continue
                row = listing_row(change, roster)
                if row is not None:
                    rows.append(row)
            if len(rows) >= CONVERSATION_FETCH_LIMIT:
                break
        if rows and not any(row.is_root for row in rows):
            oldest = self.ops.fetch_conversation_outline_page(
                mailbox_id=mailbox.id,
                conversation_id=conversation_id,
                oldest_first=True,
            )
            first = next(
                (c for c in oldest.changes if is_indexable(c, excluded_folder_ids)),
                None,
            )
            root = listing_row(first, roster) if first is not None else None
            if root is not None and root.is_root:
                rows.append(root)
        return rows

    def _copy_messages(
        self,
        mailbox: OutlookMailbox,
        conversation_id: str,
        excluded_folder_ids: set[str],
        wanted: set[str],
    ) -> list[OutlookMessage]:
        """The ``wanted`` messages of one copy with bodies, read over the
        same pages the listing or the outline covered."""

        def fetch(next_link: str | None) -> tuple[list[OutlookMessage], str | None]:
            page = self.ops.fetch_conversation_messages_page(
                mailbox_id=mailbox.id,
                conversation_id=conversation_id,
                next_link=next_link,
            )
            return page.messages, page.next_link

        # Pages arrive newest first, so the walk stops once every wanted
        # message is in hand however many drafts or trashed replies sit among them.
        kept: list[OutlookMessage] = []
        for messages in _conversation_pages(fetch, COMPARED_FETCH_LIMIT):
            kept.extend(
                m
                for m in indexable_messages(messages, excluded_folder_ids)
                if m.match_id in wanted
            )
            if len(kept) >= len(wanted):
                break
        return kept

    def _conversation_attachments(
        self, mailbox: OutlookMailbox, messages: list[OutlookMessage]
    ) -> dict[str, list[TextSection]]:
        """The attachment sections of a conversation's messages by message
        id, read once however many documents share a message."""
        attachments: dict[str, list[TextSection]] = {}
        budget = AttachmentBudget()
        for message in messages:
            if not (self.include_attachments and message.has_attachments):
                continue
            attachments[message.id] = self._attachment_sections(
                mailbox, message, budget
            )
        return attachments

    def _attachment_sections(
        self, mailbox: OutlookMailbox, message: OutlookMessage, budget: AttachmentBudget
    ) -> list[TextSection]:
        """The extracted text of a message's file attachments, one section each,
        charged to the conversation's budget.

        An attachment Graph refuses is skipped with a warning. A throttled, 5xx
        or dropped call raises like a message read does, so the checkpoint is kept.
        """
        if budget.spent:
            return []
        try:
            attachments = self.ops.list_message_attachments(
                mailbox_id=mailbox.id,
                message_id=message.id,
                limit=MAX_ATTACHMENTS_PER_MESSAGE,
            )
        except OutlookGraphError as e:
            if e.fails_the_attempt:
                raise
            logger.warning(
                "Outlook: attachments of %s unreadable (%s), skipping",
                message.id,
                e.code,
            )
            return []

        sections: list[TextSection] = []
        for attachment in attachments:
            if budget.spent:
                logger.info("Outlook: attachment budget spent in %s", message.id)
                break
            text = self._attachment_text(mailbox, message, attachment, budget)
            if not text:
                continue
            budget.text -= len(text)
            sections.append(
                TextSection(
                    link=message.web_link,
                    text=f"Attachment: {attachment.name}\n\n{text}",
                )
            )
        return sections

    def _attachment_text(
        self,
        mailbox: OutlookMailbox,
        message: OutlookMessage,
        attachment: OutlookAttachment,
        budget: AttachmentBudget,
    ) -> str:
        """One attachment's text within the budget, or "" when it is skipped:
        not worth reading, over the byte cap, refused by Graph or by the
        parsers. A transient Graph error raises."""
        reason = attachment_skip_reason(attachment)
        if reason is not None:
            logger.debug("Outlook: skipping attachment %s, %s", attachment.name, reason)
            return ""
        # Charged up front so attachments that fail still count.
        budget.reads -= 1
        try:
            data = self.ops.download_attachment(
                mailbox_id=mailbox.id,
                message_id=message.id,
                attachment_id=attachment.id,
                cap=OUTLOOK_CONNECTOR_ATTACHMENT_SIZE_THRESHOLD,
            )
        except SizeCapExceeded:
            logger.info("Outlook: skipping attachment %s over the cap", attachment.name)
            return ""
        except OutlookGraphError as e:
            if e.fails_the_attempt:
                raise
            logger.warning(
                "Outlook: attachment %s unreadable (%s), skipping",
                attachment.name,
                e.code,
            )
            return ""
        # A parser refusing the file, a crash and a timeout all cost this
        # attachment only, the way break_on_unprocessable=False would.
        try:
            return run_in_isolated_process(
                extract_attachment_text,
                data,
                attachment.name,
                budget.text,
                timeout=ATTACHMENT_EXTRACTION_TIMEOUT_SECONDS,
            )
        except Exception as e:
            logger.warning(
                "Outlook: extraction of %s failed (%s), skipping", attachment.name, e
            )
            return ""
