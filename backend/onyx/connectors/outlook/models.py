"""Plain-data shapes the Outlook gateway returns.

The gateway hands these to the connector and the capability checks instead of
raw Graph JSON, so the field names Onyx depends on are spelled out once and a
schema change in Graph surfaces here rather than deep in a document builder.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from onyx.connectors.models import ConnectorFailure, Document, HierarchyNode


class OutlookTokenInfo(BaseModel):
    expires_in: int | None = None


class OutlookMailbox(BaseModel):
    model_config = ConfigDict(frozen=True)

    # Entra object id of the user. Stable across renames, so it keys documents.
    id: str
    # The address an admin recognizes: ``mail`` when set, else the UPN.
    address: str
    display_name: str | None = None
    # The mailbox's other SMTP addresses, lower-cased, so mail sent to an
    # alias still names it.
    aliases: tuple[str, ...] = ()


class OutlookMailboxPage(BaseModel):
    mailboxes: list[OutlookMailbox]
    next_link: str | None = None


class OutlookFolder(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    display_name: str
    parent_folder_id: str | None = None
    child_folder_count: int = 0
    # Search folders show messages that live elsewhere, so walking them would
    # index the same conversation twice.
    is_search_folder: bool = False
    # Hidden folders hold client and system state, never mail a person filed,
    # so they are excluded like Junk.
    is_hidden: bool = False


class OutlookFolderPage(BaseModel):
    folders: list[OutlookFolder]
    next_link: str | None = None


class OutlookRecipient(BaseModel):
    model_config = ConfigDict(frozen=True)

    address: str
    name: str | None = None


class OutlookMessageIdentity(BaseModel):
    """What the delta listing and a conversation outline know of a message:
    where it sits, which thread it belongs to, and who it names."""

    id: str
    # The RFC 5322 Message-ID. The same in every mailbox a message was
    # delivered to, which the Graph id is not.
    internet_message_id: str | None = None
    conversation_id: str | None = None
    parent_folder_id: str | None = None
    received_at: datetime | None = None
    is_draft: bool = False
    sender: OutlookRecipient | None = None
    to_recipients: list[OutlookRecipient] = []
    cc_recipients: list[OutlookRecipient] = []

    @property
    def match_id(self) -> str:
        """The id a copy is matched by across mailboxes. A message without a
        Message-ID keeps its Graph id, so it never matches another copy."""
        return self.internet_message_id or self.id


class OutlookMessage(OutlookMessageIdentity):
    subject: str | None = None
    body_text: str = ""
    sent_at: datetime | None = None
    web_link: str | None = None
    has_attachments: bool = False


class OutlookAttachment(BaseModel):
    """One attachment record without its bytes, so the caller decides what
    to download."""

    id: str
    name: str
    size: int = 0
    # Inline attachments are embedded in the body, almost always signature images.
    is_inline: bool = False
    # Only file attachments are downloaded. Item attachments are nested
    # Outlook items and reference attachments are cloud links.
    is_file: bool = False


class OutlookMessagePage(BaseModel):
    messages: list[OutlookMessage]
    next_link: str | None = None


class OutlookMessageChange(OutlookMessageIdentity):
    """One delta entry: a message that appeared in the folder, one that left
    it, or a read-state change that Graph reports whatever the change type."""

    removed: bool = False
    conversation_index: str | None = None


class OutlookDeltaPage(BaseModel):
    changes: list[OutlookMessageChange]
    next_link: str | None = None


# Graph's event.type for one meeting expanded from a recurring series.
EVENT_OCCURRENCE = "occurrence"


class OutlookEvent(BaseModel):
    id: str
    subject: str | None = None
    body_text: str = ""
    # False when Graph sent no body property at all, which is how
    # Calendars.ReadBasic.All answers. An empty body arrives as present.
    body_present: bool = True
    start_at: datetime | None = None
    end_at: datetime | None = None
    # The zone the event was scheduled in, a Windows name. The times above are
    # UTC, so a recurring 09:00 meeting keeps its local hour only through this.
    time_zone: str | None = None
    is_all_day: bool = False
    is_cancelled: bool = False
    # normal, personal, private or confidential.
    sensitivity: str = "normal"
    # singleInstance, occurrence, exception or seriesMaster.
    event_type: str = "singleInstance"
    series_master_id: str | None = None
    organizer: OutlookRecipient | None = None
    attendees: list[OutlookRecipient] = []
    location: str | None = None
    web_link: str | None = None
    created_at: datetime | None = None
    last_modified_at: datetime | None = None
    # A plain-language recurrence pattern, series masters only.
    recurrence: str | None = None


class OutlookEventPage(BaseModel):
    events: list[OutlookEvent]
    next_link: str | None = None


class MailboxCursor(BaseModel):
    """Where the walk stands in one mailbox."""

    mailbox: OutlookMailbox
    # False until the mailbox is probed and its folder tree listed.
    opened: bool = False
    # Set when nothing is left to read. The step drops the cursor.
    finished: bool = False
    # Folders left to walk, popped from the end.
    folders: list[OutlookFolder] = []
    # Every folder id under an excluded root, so a conversation message filed
    # deep inside Deleted Items is dropped like one at its top.
    excluded_folder_ids: list[str] = []
    current_folder: OutlookFolder | None = None
    delta_next_link: str | None = None
    # Entries seen in the current folder's delta round, to detect the cap.
    folder_change_count: int = 0
    # True once the current folder is being re-read without the server filter.
    folder_unfiltered: bool = False
    # True once every folder is listed. The connector then holds the mailbox's
    # listing and builds its conversations, ``built`` of ``to_build`` so far.
    listed: bool = False
    built: int = 0
    to_build: int = 0
    # The calendar view round, one page per step after the folders.
    calendar_next_link: str | None = None
    calendar_done: bool = False
    # Recurring series already resolved for this mailbox in this attempt,
    # written or not. The connector caps it per mailbox.
    seen_series_ids: set[str] = set()


class ThreadListing(BaseModel):
    """One message of one mailbox's copy of a thread, as a listing saw it."""

    key: str
    conversation_id: str
    # The Internet Message-ID, or the Graph id when Outlook set none, so a
    # message without one is never matched across mailboxes.
    message_id: str
    received_at: datetime | None = None
    # The thread's first message, whose headers choose the builder.
    is_root: bool = False
    # The sender, when the run walks its mailbox.
    sender: OutlookMailbox | None = None
    # The walked mailboxes the message names: the sender and the recipients.
    named: list[OutlookMailbox] = []


class DocumentPlan(BaseModel):
    """One document a mailbox's copy of a thread yields: which of the copy's
    messages it holds and who reads it."""

    document_id: str
    message_ids: list[str]
    readers: list[OutlookMailbox]


class MailboxStep(BaseModel):
    """What one unit of work in one mailbox produced: items to yield and
    listing rows for the connector to hold."""

    items: list[HierarchyNode | Document | ConnectorFailure] = []
    rows: list[ThreadListing] = []
