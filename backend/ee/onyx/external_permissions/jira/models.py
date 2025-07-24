from typing import Any

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic.alias_generators import to_camel


Holder = dict[str, Any]


class Permission(BaseModel):
    id: int
    permission: str
    holder: Holder | None


class User(BaseModel):
    account_id: str
    email_address: str
    display_name: str
    active: bool

    model_config = ConfigDict(
        alias_generator=to_camel,
    )
