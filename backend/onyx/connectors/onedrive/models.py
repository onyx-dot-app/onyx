from pydantic import BaseModel, ConfigDict, Field

from onyx.connectors.microsoft_utils.drive_delta import DriveDeltaPage
from onyx.connectors.models import ConnectorCheckpoint


class OneDriveCredentials(BaseModel):
    model_config = ConfigDict(extra="ignore")

    onedrive_client_id: str
    onedrive_directory_id: str
    onedrive_client_secret: str | None = None
    onedrive_authentication_method: str | None = None
    onedrive_private_key: str | None = None
    onedrive_certificate_password: str | None = None


class OneDriveSettings(BaseModel):
    model_config = ConfigDict(frozen=True)

    users: list[str] = Field(default_factory=list)
    all_users: bool = True
    excluded_paths: list[str] = Field(default_factory=list)
    authority_host: str
    graph_api_host: str
    batch_size: int = Field(gt=0)


class OneDriveUser(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    user_principal_name: str
    mail: str | None = None
    display_name: str | None = None


class OneDriveUserPage(BaseModel):
    users: list[OneDriveUser]
    next_link: str | None = None


class OneDriveDrive(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    web_url: str | None = None


class OneDriveTokenInfo(BaseModel):
    expires_in: int | None = None


class OneDriveDeltaResult(BaseModel):
    page: DriveDeltaPage
    next_cursor: str | None = None
    resynced: bool = False


class OneDrivePermission(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str | None = None
    roles: list[str] = Field(default_factory=list)


class OneDrivePermissionPage(BaseModel):
    permissions: list[OneDrivePermission]
    next_link: str | None = None


class OneDriveGroupMember(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    display_name: str | None = Field(default=None, alias="displayName")
    mail: str | None = None
    user_principal_name: str | None = Field(default=None, alias="userPrincipalName")


class OneDriveGroupMemberPage(BaseModel):
    members: list[OneDriveGroupMember]
    next_link: str | None = None


class OneDriveCheckpoint(ConnectorCheckpoint):
    user_page: list[OneDriveUser] = Field(default_factory=list)
    users_next_link: str | None = None
    user_listing_started: bool = False
    configured_user_index: int = 0
    current_user: OneDriveUser | None = None
    current_drive: OneDriveDrive | None = None
    delta_cursor: str | None = None
    delta_started: bool = False
    seen_document_ids: set[str] = Field(default_factory=set)
    seen_hierarchy_raw_ids: set[str] = Field(default_factory=set)
