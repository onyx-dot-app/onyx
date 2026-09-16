"""Outlook connector: Microsoft 365 mail and calendar over Graph.

One document per conversation per mailbox, and with calendars on, one per event
or recurring series. Every Graph call goes through ``OutlookSourceOperations``.
The walk is mailbox by mailbox, folder by folder, then the calendar view, one
delta page per checkpoint step, so a large tenant survives worker restarts.

Incremental runs come from the poll window rather than saved delta links: an
index attempt starts from a fresh checkpoint, so each folder's delta round
opens with ``receivedDateTime ge start`` and any conversation that gained a
message in the window is rebuilt whole.

Pruning walks the same mailboxes, folders and calendar windows but reads only
conversation and event ids, so a conversation whose every message was deleted
leaves the index without a full re-index. A conversation that lost one message
keeps the stale text until it gains a message or a full re-index rebuilds it.
"""

from collections import deque
from collections.abc import Generator, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from io import BytesIO
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from babel.core import get_global

from onyx.configs.app_configs import (
    INDEX_BATCH_SIZE,
    OUTLOOK_CONNECTOR_ATTACHMENT_SIZE_THRESHOLD,
)
from onyx.configs.constants import DocumentSource
from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.interfaces import (
    CheckpointedConnector,
    CheckpointOutput,
    CredentialsConnector,
    CredentialsProviderInterface,
    GenerateSlimDocumentOutput,
    SecondsSinceUnixEpoch,
    SlimConnector,
)
from onyx.connectors.microsoft_utils.drive_items import SizeCapExceeded
from onyx.connectors.microsoft_utils.graph_env import (
    DEFAULT_AUTHORITY_HOST,
    DEFAULT_GRAPH_API_HOST,
    resolve_microsoft_environment,
)
from onyx.connectors.models import (
    BasicExpertInfo,
    ConnectorCheckpoint,
    ConnectorFailure,
    ConnectorMissingCredentialError,
    Document,
    DocumentFailure,
    EntityFailure,
    HierarchyNode,
    SlimDocument,
    TextSection,
)
from onyx.connectors.outlook.errors import (
    CALENDAR_READ_REMEDIATION,
    EXCHANGE_SCOPE_REMEDIATION,
    MAILBOX_UNAVAILABLE_REMEDIATION,
    raise_for_auth_error,
    raise_for_graph_error,
)
from onyx.connectors.outlook.mailboxes import (
    MAILBOX_UNAVAILABLE_STATUSES,
    describe_unavailable_mailboxes,
    raise_if_unavailable,
)
from onyx.connectors.outlook.models import (
    EVENT_OCCURRENCE,
    OutlookAttachment,
    OutlookAuthError,
    OutlookEvent,
    OutlookFolder,
    OutlookGraphError,
    OutlookMailbox,
    OutlookMessage,
    OutlookRecipient,
)
from onyx.connectors.outlook.source_operations import (
    CONFIG_AUTHORITY_HOST,
    CONFIG_GRAPH_API_HOST,
    OutlookSourceOperations,
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

logger = setup_logger()

# Document ids per batch handed to pruning.
SLIM_BATCH_SIZE = 500

# Skipped by default. Resolved by well-known name per mailbox, because display
# names are localized and an admin's exclusion list is not.
DEFAULT_EXCLUDED_WELL_KNOWN_FOLDERS = ("junkemail", "deleteditems", "drafts", "outbox")

# A conversation longer than this keeps only its newest indexable messages.
MAX_MESSAGES_PER_CONVERSATION = 100

# Raw messages read per conversation while looking for indexable ones, so a
# thread that is mostly drafts or trashed replies stays bounded.
CONVERSATION_FETCH_LIMIT = 500

# Conversation ids a mailbox remembers this attempt so a thread is rebuilt once
# however many of its messages the delta lists. The checkpoint is written after
# every step, so past this many the oldest ids are forgotten first.
MAX_TRACKED_CONVERSATIONS_PER_MAILBOX = 20_000

# Pages of the tenant's user listing one step may read. No tenant has this many
# users, so running past it means the paging never ends.
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

MAILBOX_NODE_PREFIX = "outlook-mailbox:"
DOCUMENT_ID_PREFIX = "outlook:"
CALENDAR_NODE_PREFIX = "outlook-calendar:"
EVENT_DOCUMENT_ID_PREFIX = "outlook-event:"

# Attendee names written into an event's text. A company all-hands lists
# hundreds and the rest add nothing a search would find.
MAX_ATTENDEES_LISTED = 50
# The calendar view needs explicit bounds. Past meetings hold the decisions
# people search for, so the window reaches further back than ahead. Pruning
# lists over the same window, so the index holds a rolling calendar.
DEFAULT_CALENDAR_PAST_DAYS = 365
DEFAULT_CALENDAR_FUTURE_DAYS = 180
# Series ids a mailbox remembers this attempt so each master is read once.
# Past this many, later series are read again per occurrence instead of
# growing the checkpoint with the size of the calendar.
MAX_TRACKED_SERIES_PER_MAILBOX = 5000
# Private hides an event's details from anyone the calendar is shared with,
# and confidential flags it as not for wider eyes. Neither belongs in a shared
# index.
SKIPPED_EVENT_SENSITIVITIES = frozenset({"private", "confidential"})


class OutlookCheckpoint(ConnectorCheckpoint):
    # None until enumerated, then the mailboxes still to walk, popped from the end.
    mailboxes: list[OutlookMailbox] | None = None
    current_mailbox: OutlookMailbox | None = None
    # None until the current mailbox's tree is listed, then folders left to walk.
    folders: list[OutlookFolder] | None = None
    # Every folder id under an excluded root, so a conversation message filed
    # deep inside Deleted Items is dropped like one at its top.
    excluded_folder_ids: list[str] = []
    current_folder: OutlookFolder | None = None
    delta_next_link: str | None = None
    # Entries seen in the current folder's delta round, to detect the cap.
    folder_change_count: int = 0
    # True once the current folder is being re-read without the server filter.
    folder_unfiltered: bool = False
    # Conversations already rebuilt for the current mailbox in this attempt,
    # oldest first, the newest MAX_TRACKED_CONVERSATIONS_PER_MAILBOX kept.
    seen_conversation_ids: dict[str, None] = {}
    # The calendar view round of the current mailbox, one page per step after
    # its folders.
    calendar_next_link: str | None = None
    calendar_done: bool = False
    # Recurring series already resolved for the current mailbox in this
    # attempt, written or not, capped at MAX_TRACKED_SERIES_PER_MAILBOX.
    seen_series_ids: set[str] = set()


def _remember_conversation(seen: dict[str, None], conversation_id: str) -> None:
    """Records a rebuilt conversation, forgetting the oldest past the cap, so a
    busy thread stays deduplicated while the checkpoint stays bounded."""
    seen[conversation_id] = None
    if len(seen) > MAX_TRACKED_CONVERSATIONS_PER_MAILBOX:
        del seen[next(iter(seen))]


def mailbox_node_id(mailbox: OutlookMailbox) -> str:
    return f"{MAILBOX_NODE_PREFIX}{mailbox.id}"


def conversation_document_id(mailbox: OutlookMailbox, conversation_id: str) -> str:
    """Keyed by mailbox because the same conversation has a different readership
    in every mailbox it sits in."""
    return f"{DOCUMENT_ID_PREFIX}{mailbox.id}:{conversation_id}"


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


def indexable_messages(
    messages: list[OutlookMessage], excluded_folder_ids: set[str]
) -> list[OutlookMessage]:
    """Drop drafts and messages sitting in excluded folders."""
    return [
        message
        for message in messages
        if not message.is_draft and message.parent_folder_id not in excluded_folder_ids
    ]


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


def _indexed_event_id(event: OutlookEvent) -> str:
    """The id the event's document is keyed by: its series master for an
    occurrence, itself otherwise."""
    return _occurrence_series_id(event) or event.id


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


def build_event_document(mailbox: OutlookMailbox, event: OutlookEvent) -> Document:
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


def build_conversation_document(
    mailbox: OutlookMailbox,
    conversation_id: str,
    messages: list[OutlookMessage],
    attachment_sections: dict[str, list[TextSection]] | None = None,
) -> Document | None:
    """Assemble indexable messages of one conversation into a document, oldest
    first, each message followed by the text of its attachments. None when
    there is nothing to index."""
    kept = sorted(messages, key=_message_sort_key)[-MAX_MESSAGES_PER_CONVERSATION:]
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
        id=conversation_document_id(mailbox, conversation_id),
        sections=sections,
        source=DocumentSource.OUTLOOK,
        semantic_identifier=subject,
        title=subject,
        doc_created_at=_message_sort_key(kept[0]),
        doc_updated_at=_message_sort_key(newest),
        primary_owners=primary_owners,
        secondary_owners=secondary_owners,
        metadata={"mailbox": mailbox.address, "message_count": str(len(kept))},
        parent_hierarchy_raw_node_id=newest.parent_folder_id
        or mailbox_node_id(mailbox),
    )


class OutlookConnector(
    CredentialsConnector, CheckpointedConnector[OutlookCheckpoint], SlimConnector
):
    def __init__(
        self,
        mailboxes: list[str] | None = None,
        excluded_folders: list[str] | None = None,
        include_attachments: bool = False,
        include_calendar: bool = False,
        calendar_past_days: int = DEFAULT_CALENDAR_PAST_DAYS,
        calendar_future_days: int = DEFAULT_CALENDAR_FUTURE_DAYS,
        authority_host: str = DEFAULT_AUTHORITY_HOST,
        graph_api_host: str = DEFAULT_GRAPH_API_HOST,
        batch_size: int = INDEX_BATCH_SIZE,
    ) -> None:
        # An empty list means every mailbox the app may open.
        self.mailboxes = [a.strip() for a in mailboxes or [] if a.strip()]
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

        if not self.mailboxes:
            try:
                self.ops.list_mailbox_users(page_size=1)
            except OutlookGraphError as e:
                raise_for_graph_error(
                    e, "The app cannot list the tenant's users for every-mailbox mode."
                )
            return
        raise_if_unavailable(describe_unavailable_mailboxes(self.ops, self.mailboxes))

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
        """One unit of work per call: enumerate, open a mailbox, or read one
        delta page. The checkpoint records where to resume."""
        if checkpoint.mailboxes is None:
            yield from self._enumerate_mailboxes(checkpoint)
            return checkpoint

        if checkpoint.current_mailbox is None:
            if not checkpoint.mailboxes:
                checkpoint.has_more = False
                return checkpoint
            yield from self._open_mailbox(checkpoint, checkpoint.mailboxes[-1])
            # Popped only once opened or skipped, so a raised Graph error
            # leaves the mailbox queued for the retry.
            checkpoint.mailboxes.pop()
            return checkpoint

        if checkpoint.current_folder is None:
            if not checkpoint.folders:
                if self.include_calendar and not checkpoint.calendar_done:
                    yield from self._read_calendar_page(checkpoint, start)
                    return checkpoint
                self._finish_mailbox(checkpoint)
                return checkpoint
            checkpoint.current_folder = checkpoint.folders.pop()
            self._reset_folder_cursor(checkpoint)

        yield from self._read_folder_page(checkpoint, start, end)
        return checkpoint

    def _reset_folder_cursor(self, checkpoint: OutlookCheckpoint) -> None:
        checkpoint.delta_next_link = None
        checkpoint.folder_change_count = 0
        checkpoint.folder_unfiltered = False

    def _finish_mailbox(self, checkpoint: OutlookCheckpoint) -> None:
        checkpoint.current_mailbox = None
        checkpoint.folders = None
        checkpoint.current_folder = None
        checkpoint.excluded_folder_ids = []
        checkpoint.seen_conversation_ids = {}
        checkpoint.calendar_next_link = None
        checkpoint.calendar_done = False
        checkpoint.seen_series_ids = set()
        self._reset_folder_cursor(checkpoint)

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
        """Unlicensed, or out of the app's Exchange scope."""
        yield from self._unavailable(
            mailbox.address,
            f"Mailbox {mailbox.address} is unavailable ({error.code}). "
            f"{EXCHANGE_SCOPE_REMEDIATION}",
            error,
        )

    def _calendar_unavailable(
        self, mailbox: OutlookMailbox, error: OutlookGraphError
    ) -> Generator[ConnectorFailure, None, None]:
        """No calendar grant, or none for this mailbox. Its mail stays indexed."""
        yield from self._unavailable(
            f"{mailbox.address} calendar",
            f"Calendar of {mailbox.address} is unavailable ({error.code}). "
            f"{CALENDAR_READ_REMEDIATION}",
            error,
        )

    def _resolve_mailboxes(
        self,
    ) -> tuple[list[OutlookMailbox], list[ConnectorFailure]]:
        """The mailboxes to walk, in configured order, plus a failure per
        configured address that matches no user."""
        found: list[OutlookMailbox] = []
        failures: list[ConnectorFailure] = []
        if self.mailboxes:
            for address in self.mailboxes:
                # Resolution reads the directory, never the mailbox, so a Graph
                # error here is about the app or the service and fails the
                # attempt instead of dropping the address.
                mailbox = self.ops.resolve_mailbox(address=address)
                if mailbox is None:
                    failures.append(
                        _mailbox_failure(
                            address,
                            f"No user matches {address}. "
                            f"{MAILBOX_UNAVAILABLE_REMEDIATION}",
                        )
                    )
                    continue
                found.append(mailbox)
        else:
            # TODO(nmgarza5): list across checkpoint steps and carry compact
            # mailbox records, so a huge tenant survives a failure mid-listing.
            next_link: str | None = None
            for _ in range(MAX_MAILBOX_LISTING_PAGES):
                page = self.ops.list_mailbox_users(next_link=next_link)
                found.extend(page.mailboxes)
                next_link = page.next_link
                if next_link is None:
                    break
            if next_link is not None:
                raise RuntimeError(
                    "Outlook: the user listing ran past "
                    f"{MAX_MAILBOX_LISTING_PAGES} pages without ending"
                )
        # A UPN and a primary SMTP address, or two listing pages, can name the
        # same mailbox. The dict keeps the first occurrence in order.
        unique = list({mailbox.id: mailbox for mailbox in found}.values())
        logger.info("Outlook: %s mailboxes to walk", len(unique))
        return unique, failures

    def _enumerate_mailboxes(
        self, checkpoint: OutlookCheckpoint
    ) -> Generator[ConnectorFailure, None, None]:
        mailboxes, failures = self._resolve_mailboxes()
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
        """Every conversation and event document id the walk would produce
        today, so pruning drops the ones that vanished.

        Reads folder and delta metadata only, never a body. A mailbox whose
        probe answers 404 is gone and contributes nothing, so its documents go
        too. Any other Graph failure raises: an aborted prune deletes nothing,
        while a silent skip would delete every document of that mailbox.
        """
        del start, end
        mailboxes, failures = self._resolve_mailboxes()
        # An address that matches no user is a configuration problem, not a
        # verdict on the mailbox behind it, so the prune stops here rather than
        # treat every conversation of that mailbox as gone.
        if failures:
            addresses = ", ".join(
                failure.failed_entity.entity_id
                for failure in failures
                if failure.failed_entity is not None
            )
            raise ConnectorValidationError(
                f"Cannot prune while these mailboxes match no user: {addresses}. "
                "Fix or remove them from the mailbox list."
            )
        for mailbox in mailboxes:
            try:
                self.ops.probe_mailbox(mailbox_id=mailbox.id)
            except OutlookGraphError as e:
                if e.status == 404:
                    logger.info("Outlook: %s is gone, pruning it", mailbox.address)
                    continue
                raise
            # A 404 past the probe is a folder that vanished mid-walk, not the
            # mailbox, so it aborts the prune like any other error.
            excluded = self._excluded_well_known_folder_ids(mailbox)
            tree = list(self._walk_folder_tree(mailbox, excluded))
            yield list(self._hierarchy_nodes(mailbox, tree))
            yield from self._slim_batches(
                self._conversation_id_pages(mailbox, tree), callback
            )
            if self.include_calendar:
                yield from self._slim_batches(self._event_id_pages(mailbox), callback)

    def _slim_batches(
        self, id_pages: Iterable[list[str]], callback: IndexingHeartbeatInterface | None
    ) -> GenerateSlimDocumentOutput:
        """Document ids batched across pages, each page reported to the heartbeat."""
        batch: list[SlimDocument | HierarchyNode] = []
        for ids in id_pages:
            batch.extend(SlimDocument(id=document_id) for document_id in ids)
            while len(batch) >= SLIM_BATCH_SIZE:
                yield batch[:SLIM_BATCH_SIZE]
                batch = batch[SLIM_BATCH_SIZE:]
            if callback is not None:
                callback.progress("outlook_slim_docs", len(ids))
        if batch:
            yield batch

    def _conversation_id_pages(
        self, mailbox: OutlookMailbox, tree: list[tuple[OutlookFolder, str]]
    ) -> Generator[list[str], None, None]:
        """Conversation document ids of every folder in the tree, one list per
        delta page and deduplicated within it. The parent is left unset so
        pruning keeps the folder indexing chose. Any Graph error raises, since
        pruning must see the whole mailbox or nothing."""
        for folder, _ in tree:
            next_link: str | None = None
            while True:
                # A 410 mid-round is not restarted here: ids already yielded
                # from the expired round cannot be retracted, so the prune
                # aborts and runs again later.
                page = self.ops.fetch_folder_delta_page(
                    mailbox_id=mailbox.id, folder_id=folder.id, next_link=next_link
                )
                conversation_ids = dict.fromkeys(
                    change.conversation_id
                    for change in page.changes
                    if not change.removed and change.conversation_id
                )
                yield [
                    conversation_document_id(mailbox, conversation_id)
                    for conversation_id in conversation_ids
                ]
                next_link = page.next_link
                if next_link is None:
                    break

    def _event_id_pages(
        self, mailbox: OutlookMailbox
    ) -> Generator[list[str], None, None]:
        """Event document ids of the calendar window, admitted by the rule
        indexing applies: skips on the row, and a series only when its master
        is readable and not excluded, read once per series per mailbox. Ids
        are deduplicated per page only, since pruning reads them as a set.

        A calendar that is gone (404 on the first page) lists nothing, so its
        events are pruned like the mail of a vanished mailbox. A refused one
        (403) aborts the prune with the grant to fix: listing nothing would
        prune its events, and the poll window skips unchanged events, so they
        would return only with a full re-index. An error later in the round
        raises, since the ids already listed cannot be retracted.
        """
        window_start, window_end = self._calendar_window()
        # Capped like the checkpoint's set, so a huge calendar costs repeat
        # master reads rather than memory.
        series_included: dict[str, bool] = {}
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
                        "Outlook: calendar of %s is gone, pruning its events",
                        mailbox.address,
                    )
                    return
                if e.status == 403 and next_link is None:
                    raise ConnectorValidationError(
                        f"Cannot prune while the calendar of {mailbox.address} "
                        f"is refused ({e.code}). {CALENDAR_READ_REMEDIATION} "
                        "Or turn Include Calendar off."
                    ) from e
                raise
            event_ids: dict[str, None] = {}
            for event in page.events:
                if event_skip_reason(event) is not None:
                    continue
                series_id = _occurrence_series_id(event)
                if series_id is None:
                    event_ids[event.id] = None
                    continue
                if series_id not in series_included:
                    included = (
                        self._indexable_series_master(mailbox, series_id) is not None
                    )
                    if len(series_included) < MAX_TRACKED_SERIES_PER_MAILBOX:
                        series_included[series_id] = included
                elif not series_included[series_id]:
                    continue
                else:
                    included = True
                if included:
                    event_ids[series_id] = None
            yield [event_document_id(mailbox, event_id) for event_id in event_ids]
            next_link = page.next_link
            if next_link is None:
                break

    def _open_mailbox(
        self, checkpoint: OutlookCheckpoint, mailbox: OutlookMailbox
    ) -> Generator[HierarchyNode | ConnectorFailure, None, None]:
        """Probe the mailbox, then list its whole folder tree.

        Nothing is yielded until the tree is known, so a listing that fails
        part way leaves nothing behind for the retry to repeat.
        """
        try:
            self.ops.probe_mailbox(mailbox_id=mailbox.id)
            excluded = self._excluded_well_known_folder_ids(mailbox)
            tree = list(self._walk_folder_tree(mailbox, excluded))
        except OutlookGraphError as e:
            if e.status not in MAILBOX_UNAVAILABLE_STATUSES:
                raise
            yield from self._mailbox_unavailable(mailbox, e)
            return

        yield from self._hierarchy_nodes(mailbox, tree)

        checkpoint.current_mailbox = mailbox
        checkpoint.folders = list(reversed([folder for folder, _ in tree]))
        checkpoint.excluded_folder_ids = sorted(excluded)
        checkpoint.current_folder = None
        checkpoint.seen_conversation_ids = {}
        checkpoint.calendar_next_link = None
        checkpoint.calendar_done = False
        checkpoint.seen_series_ids = set()
        self._reset_folder_cursor(checkpoint)

    def _hierarchy_nodes(
        self, mailbox: OutlookMailbox, tree: list[tuple[OutlookFolder, str]]
    ) -> Generator[HierarchyNode, None, None]:
        yield HierarchyNode(
            raw_node_id=mailbox_node_id(mailbox),
            raw_parent_id=None,
            display_name=mailbox.display_name or mailbox.address,
            link=_mailbox_link(mailbox),
            node_type=HierarchyNodeType.MAILBOX,
        )
        for folder, parent_node_id in tree:
            yield HierarchyNode(
                raw_node_id=folder.id,
                raw_parent_id=parent_node_id,
                display_name=folder.display_name,
                node_type=HierarchyNodeType.FOLDER,
            )
        if self.include_calendar:
            yield HierarchyNode(
                raw_node_id=calendar_node_id(mailbox),
                raw_parent_id=mailbox_node_id(mailbox),
                display_name="Calendar",
                link=_calendar_link(mailbox),
                node_type=HierarchyNodeType.FOLDER,
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
        checkpoint: OutlookCheckpoint,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
    ) -> Generator[Document | ConnectorFailure, None, None]:
        mailbox = checkpoint.current_mailbox
        folder = checkpoint.current_folder
        assert mailbox is not None and folder is not None

        window_start = _poll_bound(start)
        try:
            page = self.ops.fetch_folder_delta_page(
                mailbox_id=mailbox.id,
                folder_id=folder.id,
                received_after=None if checkpoint.folder_unfiltered else window_start,
                next_link=checkpoint.delta_next_link,
            )
        except OutlookGraphError as e:
            # Graph drops delta state with 410. Start the folder's round over.
            if e.status == 410 and checkpoint.delta_next_link is not None:
                checkpoint.delta_next_link = None
                checkpoint.folder_change_count = 0
                return
            # The folder disappeared mid-run. Nothing left to index in it.
            if e.status == 404:
                logger.info(
                    "Outlook: folder %s in %s vanished, skipping",
                    folder.display_name,
                    mailbox.address,
                )
                checkpoint.current_folder = None
                return
            # Access to the whole mailbox is gone, so stop walking it rather
            # than record one failure per remaining folder.
            if e.status == 403:
                yield from self._mailbox_unavailable(mailbox, e)
                self._finish_mailbox(checkpoint)
                return
            raise

        end_at = _poll_bound(end)
        excluded = set(checkpoint.excluded_folder_ids)
        for change in page.changes:
            if change.removed or not change.conversation_id:
                continue
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
            if change.conversation_id in checkpoint.seen_conversation_ids:
                continue
            result = self._rebuild_conversation(
                mailbox, change.conversation_id, excluded
            )
            _remember_conversation(
                checkpoint.seen_conversation_ids, change.conversation_id
            )
            if result is not None:
                yield result

        # Committed with the cursor, so a page replayed after a failure part
        # way through is counted once.
        checkpoint.folder_change_count += len(page.changes)
        checkpoint.delta_next_link = page.next_link
        if page.next_link is not None:
            return
        filled_cap = (
            window_start is not None
            and not checkpoint.folder_unfiltered
            and checkpoint.folder_change_count >= FILTERED_DELTA_CAP
        )
        if filled_cap:
            logger.info(
                "Outlook: folder %s in %s filled the filtered delta cap, "
                "re-reading it without the filter",
                folder.display_name,
                mailbox.address,
            )
            self._reset_folder_cursor(checkpoint)
            checkpoint.folder_unfiltered = True
            return
        checkpoint.current_folder = None

    def _calendar_window(self) -> tuple[datetime, datetime]:
        """The event times the calendar view covers, around the moment of the call."""
        now = datetime.now(timezone.utc)
        return (
            now - timedelta(days=self.calendar_past_days),
            now + timedelta(days=self.calendar_future_days),
        )

    def _read_calendar_page(
        self, checkpoint: OutlookCheckpoint, start: SecondsSinceUnixEpoch
    ) -> Generator[Document | ConnectorFailure, None, None]:
        mailbox = checkpoint.current_mailbox
        assert mailbox is not None

        window_start, window_end = self._calendar_window()
        try:
            page = self.ops.fetch_calendar_delta_page(
                mailbox_id=mailbox.id,
                window_start=window_start,
                window_end=window_end,
                next_link=checkpoint.calendar_next_link,
            )
        except OutlookGraphError as e:
            # Graph drops delta state with 410. Start the round over.
            if e.status == 410 and checkpoint.calendar_next_link is not None:
                checkpoint.calendar_next_link = None
                return
            if e.status in MAILBOX_UNAVAILABLE_STATUSES:
                yield from self._calendar_unavailable(mailbox, e)
                checkpoint.calendar_done = True
                return
            raise

        modified_after = _poll_bound(start)
        for event in page.events:
            document = self._event_document(
                mailbox, event, modified_after, checkpoint.seen_series_ids
            )
            if document is not None:
                yield document
        checkpoint.calendar_next_link = page.next_link
        checkpoint.calendar_done = page.next_link is None

    def _event_document(
        self,
        mailbox: OutlookMailbox,
        event: OutlookEvent,
        modified_after: datetime | None,
        seen_series_ids: set[str],
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
        return build_event_document(mailbox, event)

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

    def _rebuild_conversation(
        self,
        mailbox: OutlookMailbox,
        conversation_id: str,
        excluded_folder_ids: set[str],
    ) -> Document | ConnectorFailure | None:
        document_id = conversation_document_id(mailbox, conversation_id)
        # Pages arrive newest first, so the walk stops at the newest indexable
        # messages however many drafts or trashed replies sit among them.
        kept: list[OutlookMessage] = []
        fetched = 0
        next_link: str | None = None
        try:
            while True:
                page = self.ops.fetch_conversation_messages_page(
                    mailbox_id=mailbox.id,
                    conversation_id=conversation_id,
                    next_link=next_link,
                )
                # The budget applies to raw messages, so a final page is cut
                # to what is left of it before filtering.
                within_budget = page.messages[: CONVERSATION_FETCH_LIMIT - fetched]
                fetched += len(within_budget)
                kept.extend(indexable_messages(within_budget, excluded_folder_ids))
                next_link = page.next_link
                if (
                    next_link is None
                    or len(kept) >= MAX_MESSAGES_PER_CONVERSATION
                    or fetched >= CONVERSATION_FETCH_LIMIT
                ):
                    break
            # Cut here so attachments are read only for the messages the
            # document keeps.
            kept = kept[:MAX_MESSAGES_PER_CONVERSATION]
            attachments: dict[str, list[TextSection]] = {}
            budget = AttachmentBudget()
            for message in kept:
                if not (self.include_attachments and message.has_attachments):
                    continue
                attachments[message.id] = self._attachment_sections(
                    mailbox, message, budget
                )
        except OutlookGraphError as e:
            # A recorded failure lets the poll window move past the mail, so a
            # transient failure raises and keeps the checkpoint for the retry.
            if e.fails_the_attempt:
                raise
            return ConnectorFailure(
                failed_document=DocumentFailure(document_id=document_id),
                failure_message=(
                    f"Failed to fetch conversation {conversation_id} in "
                    f"{mailbox.address}: {e}"
                ),
                exception=e,
            )
        return build_conversation_document(mailbox, conversation_id, kept, attachments)

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
