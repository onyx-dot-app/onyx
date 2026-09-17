from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


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
    display_name: str | None = None
    email: str | None = None
    user_id: str | None = None

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
