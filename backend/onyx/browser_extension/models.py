"""The data of the relay between chat turns and the user's Chrome
(`relay.py`) and of its single-use socket tokens (`tokens.py`)."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, JsonValue


class ExtensionTokenData(BaseModel):
    user_id: UUID
    tenant_id: str


class Installation(BaseModel):
    """A connected Chrome with the Onyx extension, as the web app sees it."""

    installation_id: UUID
    label: str = Field(max_length=200)
    version: str = Field(max_length=50)


class Presence(Installation):
    # The installation's current socket; a newer one replaces it.
    connection_id: str


class GrantTab(BaseModel):
    id: str = Field(max_length=50)
    title: str = Field(default="", max_length=500)
    url: str = Field(default="", max_length=2048)


class SharedTabs(BaseModel):
    """What the user shared with one chat, as the web app sees it."""

    tabs: list[GrantTab] = Field(max_length=50)
    origins: list[str] = Field(max_length=50)
    expires_at: float


class ChromeGrant(SharedTabs):
    user_id: UUID
    installation_id: UUID
    chat_session_id: UUID


class GrantReport(SharedTabs):
    """A grant as the extension reports it: on approval (with the request)
    and after each change of its tabs."""

    chat_session_id: UUID
    request_id: str | None = None


class GrantRequest(BaseModel):
    """The chat's one share request; a newer request replaces it."""

    request_id: str
    user_id: UUID
    installation_id: UUID
    state: Literal["pending", "denied"]


class CommandError(BaseModel):
    message: str = Field(max_length=4000)


class CommandResult(BaseModel):
    ok: bool
    result: dict[str, JsonValue] | None = None
    error: CommandError | None = None
