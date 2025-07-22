from datetime import datetime

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
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

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )
