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
    # `scheme://host[:port]`; empty when unknown
    origin: str = Field(default="", max_length=300)
    # "human" while the user's own input holds the tab
    controller: Literal["agent", "human"] = "agent"


class ChromeGrant(BaseModel):
    """The access of one installation to one chat. The allowed sites are not
    stored: they are the chat's session approvals plus `once_origins`."""

    user_id: UUID
    installation_id: UUID
    chat_session_id: UUID
    chat_title: str = Field(max_length=500)
    tabs: list[GrantTab] = Field(max_length=50)
    current: str | None = None
    expires_at: float
    # True when the extension's side panel started the binding; the extension
    # ends it when the panel closes.
    side_panel: bool
    window_id: int | None = None
    # Sites that "Approve once" allowed, for the response with this id.
    once_origins: list[str] = Field(default_factory=list, max_length=50)
    once_response_id: int | None = None


class GrantReport(BaseModel):
    """A grant's tabs as the extension reports them after a bind and after
    each change."""

    chat_session_id: UUID
    tabs: list[GrantTab] = Field(max_length=50)
    current: str | None = None


class CommandError(BaseModel):
    message: str = Field(max_length=4000)


class CommandResult(BaseModel):
    ok: bool
    result: dict[str, JsonValue] | None = None
    error: CommandError | None = None
