from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from onyx.connectors.microsoft_utils.drive_delta import DriveDeltaItem, DriveDeltaPage
from onyx.connectors.microsoft_utils.graph_env import (
    DEFAULT_AUTHORITY_HOST,
    DEFAULT_GRAPH_API_HOST,
)
from onyx.connectors.models import ConnectorCheckpoint


class OneDriveCredentials(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    onedrive_client_id: str
    onedrive_directory_id: str
    onedrive_client_secret: str | None = None
    onedrive_authentication_method: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "onedrive_authentication_method", "authentication_method"
        ),
    )
    onedrive_private_key: str | None = None
    onedrive_certificate_password: str | None = None


class OneDriveConnectorConfig(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    users: list[str] = Field(default_factory=list)
    authority_host: str = DEFAULT_AUTHORITY_HOST
    graph_api_host: str = DEFAULT_GRAPH_API_HOST

    @property
    def indexes_all_users(self) -> bool:
        return not self.users


class OneDriveSettings(OneDriveConnectorConfig):
    excluded_paths: list[str] = Field(default_factory=list)


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


class OneDriveDiscoveredFile(BaseModel):
    model_config = ConfigDict(frozen=True)

    drive: OneDriveDrive
    item: DriveDeltaItem


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
    user_listing_pages: int = 0
    configured_user_index: int = 0
    current_user: OneDriveUser | None = None
    current_drive: OneDriveDrive | None = None
    delta_cursor: str | None = None
    delta_started: bool = False
    delta_pages: int = 0
