from typing import NotRequired

from pydantic import BaseModel
from typing_extensions import TypedDict

from onyx.connectors.capability_checks.models import CheckRowText


class ChannelTopicPurposeType(TypedDict):
    """
    Represents the topic or purpose of a Slack channel.
    """

    value: str
    creator: str
    last_set: int


class ChannelType(TypedDict):
    """
    Represents a Slack channel.
    """

    id: str
    name: str
    is_channel: bool
    is_group: bool
    is_im: bool
    created: int
    creator: str
    is_archived: bool
    is_general: bool
    unlinked: int
    name_normalized: str
    is_shared: bool
    is_ext_shared: bool
    is_org_shared: bool
    pending_shared: list[str]
    is_pending_ext_shared: bool
    is_member: bool
    is_private: bool
    is_mpim: bool
    updated: int
    topic: ChannelTopicPurposeType
    purpose: ChannelTopicPurposeType
    previous_names: list[str]
    num_members: int
    team: NotRequired[str]
    context_team_id: NotRequired[str]
    shared_team_ids: NotRequired[list[str]]


class AttachmentType(TypedDict):
    """
    Represents a Slack message attachment.
    """

    service_name: NotRequired[str]
    text: NotRequired[str]
    fallback: NotRequired[str]
    thumb_url: NotRequired[str]
    thumb_width: NotRequired[int]
    thumb_height: NotRequired[int]
    id: NotRequired[int]


class BotProfileType(TypedDict):
    """
    Represents a Slack bot profile.
    """

    id: NotRequired[str]
    deleted: NotRequired[bool]
    name: NotRequired[str]
    updated: NotRequired[int]
    app_id: NotRequired[str]
    team_id: NotRequired[str]


class MessageType(TypedDict):
    """
    Represents a Slack message.
    """

    type: str
    user: str
    text: str
    ts: str
    attachments: NotRequired[list[AttachmentType]]
    # Bot-related fields
    bot_id: NotRequired[str]
    app_id: NotRequired[str]
    bot_profile: NotRequired[BotProfileType]
    # Message threading
    thread_ts: NotRequired[str]
    # Message subtype (for filtering certain message types)
    subtype: NotRequired[str]


# list of messages in a thread
ThreadType = list[MessageType]


class Rejection(BaseModel):
    message: str
    row: CheckRowText


class GridTeam(BaseModel):
    id: str
    name: str | None


class HistoryRows(BaseModel):
    history_denied: str
    history_denied_row: CheckRowText
    replies_denied: str
    replies_denied_row: CheckRowText


class ChannelPattern(BaseModel):
    pattern: str
    # How the message and the row name the pattern's field.
    label: str
    line: str
