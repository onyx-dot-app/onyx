from enum import StrEnum
from typing import Any

from pydantic import BaseModel


class ZendeskRole(StrEnum):
    END_USER = "end-user"
    AGENT = "agent"
    ADMIN = "admin"


class ZendeskUser(BaseModel):
    id: int
    name: str | None = None
    email: str | None = None
    role: str | None = None
    custom_role_id: int | None = None
    suspended: bool = False

    @property
    def is_staff(self) -> bool:
        """Agents and admins read internal notes. Any other role, or none,
        counts as an end user."""
        return self.role in (ZendeskRole.AGENT, ZendeskRole.ADMIN)

    @property
    def grantable_email(self) -> str | None:
        """The email to grant documents to, if the user can still sign in."""
        if self.suspended or not self.email:
            return None
        return self.email.lower()


class ZendeskGroup(BaseModel):
    id: int
    # Private groups exist only on Enterprise plans.
    is_public: bool = True


class ZendeskOrganization(BaseModel):
    id: int
    # Whether the organization's end users can read each other's tickets.
    shared_tickets: bool = False


class ZendeskPageResponse(BaseModel):
    data: list[dict[str, Any]]
    meta: dict[str, Any]
    has_more: bool


class ZendeskTicketPage(ZendeskPageResponse):
    """A ticket export page. The users, groups and organizations the tickets
    name are present only when the page was read with access."""

    users: list[ZendeskUser] = []
    groups: list[ZendeskGroup] = []
    organizations: list[ZendeskOrganization] = []
