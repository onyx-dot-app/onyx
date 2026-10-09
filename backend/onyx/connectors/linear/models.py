from enum import Enum

from pydantic import BaseModel


class TeamVisibility(str, Enum):
    PUBLIC = "public"
    PRIVATE = "private"
    # A non-private sub-team of a private team: readable by the parent's
    # members without joining. Team.private says false for it, so never read
    # that field.
    RESTRICTED = "restricted"


class LinearTeam(BaseModel):
    id: str
    key: str
    visibility: TeamVisibility
    parent_id: str | None = None


class LinearUser(BaseModel):
    email: str
    active: bool
    guest: bool
    app: bool


class IssueShare(BaseModel):
    """What an issue adds to sharing: the people it names, and whether it
    takes its parent's."""

    parent_id: str | None
    inherits: bool
    emails: set[str]


class WorkspaceMembers(BaseModel):
    """The workspace's id, which names its members group, and the emails of
    its active non-guest, non-app users."""

    organization_id: str
    emails: set[str]
