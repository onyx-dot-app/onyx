"""Plain-data shapes the Outlook gateway returns.

The gateway hands these to the connector and the capability checks instead of
raw Graph JSON, so the field names Onyx depends on are spelled out once and a
schema change in Graph surfaces here rather than deep in a document builder.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class OutlookTokenInfo(BaseModel):
    expires_in: int | None = None


class OutlookMailbox(BaseModel):
    model_config = ConfigDict(frozen=True)

    # Entra object id of the user. Stable across renames, so it keys documents.
    id: str
    # The address an admin recognizes: ``mail`` when set, else the UPN.
    address: str
    display_name: str | None = None


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


class OutlookMessage(BaseModel):
    id: str
    conversation_id: str | None = None
    parent_folder_id: str | None = None
    subject: str | None = None
    body_text: str = ""
    sender: OutlookRecipient | None = None
    to_recipients: list[OutlookRecipient] = []
    cc_recipients: list[OutlookRecipient] = []
    received_at: datetime | None = None
    sent_at: datetime | None = None
    web_link: str | None = None
    is_draft: bool = False
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


class OutlookMessageChange(BaseModel):
    """One delta entry: a message that appeared in the folder, one that left
    it, or a read-state change that Graph reports whatever the change type."""

    id: str
    removed: bool = False
    conversation_id: str | None = None
    received_at: datetime | None = None


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
