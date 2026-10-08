from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from onyx.connectors.models import ConnectorFailure, Document


class Body(BaseModel):
    content_type: str
    content: str | None

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class User(BaseModel):
    id: str
    display_name: str

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class From(BaseModel):
    user: User | None

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class ChannelMember(BaseModel):
    email: str | None = None
    user_id: str | None = None

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class ChannelIdentity(BaseModel):
    """Which channel a message is in. Only the team-wide export needs it, whose
    rows mix channels."""

    team_id: str | None = None
    channel_id: str | None = None

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class ChatExportRow(BaseModel):
    """The two fields a poll reads from a row of a user's chats export: which
    chat changed and on which day."""

    chat_id: str | None = None
    created_date_time: datetime

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class Message(BaseModel):
    id: str
    replyToId: str | None
    subject: str | None
    from_: From | None = Field(alias="from")
    body: Body
    created_date_time: datetime
    last_modified_date_time: datetime | None
    last_edited_date_time: datetime | None
    deleted_date_time: datetime | None
    web_url: str
    # Graph also lists system events (member added, channel renamed) as messages.
    message_type: str | None = None
    channel_identity: ChannelIdentity | None = None

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )

    @property
    def is_indexable(self) -> bool:
        """A deleted message keeps its row with an empty body, and a system
        event carries no conversation."""
        if self.deleted_date_time is not None:
            return False
        return self.message_type in (None, "message")


class ChannelRef(BaseModel):
    """What a checkpoint keeps of a channel: enough to walk it and name its threads."""

    team_id: str
    id: str
    display_name: str
    # "standard" is read by the whole team, anything else has a member list of
    # its own. A checkpoint saved without it reads it from Graph before a walk.
    membership_type: str | None = None


class ChannelCursor(BaseModel):
    """A channel the walk is inside, and the page it reads next. No page url
    means the channel's first page."""

    channel: ChannelRef
    next_messages_url: str | None = None


class ChannelAdvance(BaseModel):
    """What one worker brings back from a channel's page."""

    cursor: ChannelCursor
    items: list[Document | ConnectorFailure]
    done: bool = False
    restarted: bool = False


class TeamExport(BaseModel):
    """What a team's export stream leaves for the step once its documents are
    out: the team's channels, and whether they go to the channel walk."""

    channels: list[ChannelRef]
    # The stream was refused or too large to hold, so the channels go to the
    # channel walk.
    fell_back: bool = False
    # The refusal was a 402, which applies to the whole tenant.
    refused_to_app: bool = False


class ChannelLibrary(BaseModel):
    drive_id: str
    list_id: str
    site_url: str
    folder_id: str
