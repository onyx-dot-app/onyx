"""The plain data SharePoint permission sync works on: principals and role
assignments from SharePoint REST, and the members of an Entra group from
Graph. The office365 objects never leave ``sharepoint_rest``."""

from enum import Enum

from pydantic import BaseModel, ConfigDict


class SharepointPrincipal(BaseModel):
    """A user, Entra group or SharePoint group from a role assignment or a site
    group."""

    model_config = ConfigDict(frozen=True)

    principal_type: int
    login_name: str
    title: str
    user_principal_name: str | None = None


class SharepointRoleAssignment(BaseModel):
    model_config = ConfigDict(frozen=True)

    member: SharepointPrincipal | None
    role_type_kinds: list[int]


class SharepointSecurableKind(str, Enum):
    SITE = "site"
    LIBRARY = "library"
    LIST_ITEM = "list_item"
    PAGE = "page"
    FOLDER = "folder"


class SharepointSecurable(BaseModel):
    """The object whose role assignments to read, within one site."""

    model_config = ConfigDict(frozen=True)

    kind: SharepointSecurableKind
    list_id: str | None = None
    item_id: int | None = None
    # A site page's absolute web URL.
    page_url: str | None = None
    folder_unique_id: str | None = None


class EntraMemberKind(str, Enum):
    USER = "user"
    GROUP = "group"
    UNKNOWN = "unknown"


class EntraMember(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: EntraMemberKind
    id: str
    display_name: str | None = None
    user_principal_name: str | None = None
    mail: str | None = None
