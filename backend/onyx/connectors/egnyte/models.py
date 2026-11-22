from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class EgnyteLockInfo(BaseModel):
    first_name: str = ""
    last_name: str = ""


class EgnyteFile(BaseModel):
    name: str
    path: str
    # Identifies the file across versions. ``entry_id`` names one version.
    group_id: str
    entry_id: str
    # RFC 1123 date, e.g. "Tue, 10 Nov 2026 18:00:00 GMT".
    last_modified: str
    uploaded_by: str | None = None
    lock_info: EgnyteLockInfo | None = None


class EgnyteFolder(BaseModel):
    name: str
    path: str
    folder_id: str
    # None for the domain root.
    parent_id: str | None = None


class EgnytePermissionGrant(BaseModel):
    # A username, or a group's display name.
    subject: str
    # None, Viewer Only, Viewer, Editor, Full or Owner.
    permission: str


class EgnytePermissions(BaseModel):
    """A folder's effective grants, inherited ones included."""

    users: list[EgnytePermissionGrant] = Field(default_factory=list)
    groups: list[EgnytePermissionGrant] = Field(default_factory=list)


class EgnyteFolderPage(BaseModel):
    """One page of a folder's direct children, with the folder itself."""

    folder: EgnyteFolder
    folders: list[EgnyteFolder]
    files: list[EgnyteFile]
    # Set only when the page was read with the folder's permissions.
    permissions: EgnytePermissions | None = None


class EgnyteUserType(str, Enum):
    ADMIN = "admin"
    POWER = "power"
    STANDARD = "standard"


class EgnyteUser(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    user_name: str = Field(alias="userName")
    email: str
    user_type: EgnyteUserType = Field(alias="userType")
    active: bool


class EgnyteUserInfo(BaseModel):
    """The token's own user."""

    username: str
    user_type: EgnyteUserType


class EgnyteGroupRef(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    display_name: str = Field(alias="displayName")


class EgnyteGroupMember(BaseModel):
    username: str


class EgnyteGroup(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    display_name: str = Field(alias="displayName")
    members: list[EgnyteGroupMember] = Field(default_factory=list)


class EgnyteDirectory(BaseModel):
    """What folder grants need to become Onyx access: each active user's email
    by username, and each custom group's id by display name."""

    emails_by_username: dict[str, str]
    group_ids_by_name: dict[str, str]
