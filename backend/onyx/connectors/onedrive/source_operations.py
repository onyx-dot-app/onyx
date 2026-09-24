from typing import Any
from urllib.parse import quote

import requests

from onyx.configs.app_configs import SHAREPOINT_CONNECTOR_SIZE_THRESHOLD
from onyx.configs.constants import DocumentSource
from onyx.connectors.capabilities import CredentialCapability
from onyx.connectors.microsoft_utils.drive_delta import (
    DRIVE_DELTA_SELECT_FIELDS,
    build_onedrive_delta_request_headers,
    fetch_drive_delta_checkpoint_page,
)
from onyx.connectors.microsoft_utils.drive_items import (
    DriveItemContent,
    DriveItemData,
    extract_drive_item_content,
)
from onyx.connectors.microsoft_utils.graph_client import GraphApiClient
from onyx.connectors.microsoft_utils.graph_env import (
    DEFAULT_AUTHORITY_HOST,
    DEFAULT_GRAPH_API_HOST,
)
from onyx.connectors.microsoft_utils.graph_errors import (
    MISSING_CREDENTIAL_CODE,
    microsoft_error_from_exception,
)
from onyx.connectors.microsoft_utils.graph_errors import (
    MicrosoftAuthError as OneDriveAuthError,
)
from onyx.connectors.microsoft_utils.graph_errors import (
    MicrosoftGraphError as OneDriveGraphError,
)
from onyx.connectors.microsoft_utils.graph_gateway import (
    MicrosoftGraphAuthConfig,
    MicrosoftGraphGateway,
    build_graph_user_url,
)
from onyx.connectors.onedrive.models import (
    OneDriveCredentials,
    OneDriveDeltaResult,
    OneDriveDrive,
    OneDriveGroup,
    OneDriveGroupMember,
    OneDriveGroupMemberPage,
    OneDriveGroupPage,
    OneDrivePermission,
    OneDrivePermissionPage,
    OneDriveTokenInfo,
    OneDriveUser,
    OneDriveUserPage,
)
from onyx.connectors.source_operations import (
    OperationConsumes,
    SourceOperations,
    source_operation,
)
from onyx.file_store.staging import RawFileCallback

GRAPH_API_VERSION = "v1.0"
USERS_PAGE_SIZE = 999
USER_SELECT = "id,userPrincipalName,mail,displayName,userType,accountEnabled"
GROUP_SELECT = "id,displayName,visibility"
GROUP_MEMBER_SELECT = "id,displayName,userPrincipalName,mail"
GROUPS_PAGE_SIZE = 999
CONFIG_AUTHORITY_HOST = "authority_host"
CONFIG_GRAPH_API_HOST = "graph_api_host"
CONFIG_USERS = "users"


def _user(raw: dict[str, Any]) -> OneDriveUser | None:
    if (
        not raw.get("id")
        or not raw.get("userPrincipalName")
        or raw.get("accountEnabled") is False
        or raw.get("userType") == "Guest"
    ):
        return None
    return OneDriveUser(
        id=raw["id"],
        user_principal_name=raw["userPrincipalName"],
        mail=raw.get("mail"),
        display_name=raw.get("displayName"),
    )


class OneDriveSourceOperations(SourceOperations):
    source = DocumentSource.ONEDRIVE
    sdk_modules = ("msal", "requests")

    _graph_gateway: MicrosoftGraphGateway | None = None

    def _config(self, key: str, default: str) -> str:
        return str((self.connector_specific_config or {}).get(key) or default).rstrip(
            "/"
        )

    def _graph_host(self) -> str:
        return self._config(CONFIG_GRAPH_API_HOST, DEFAULT_GRAPH_API_HOST)

    def _base(self) -> str:
        return self._gateway().graph_api_base

    def _credentials(self) -> OneDriveCredentials:
        try:
            return OneDriveCredentials.model_validate(
                self.credentials_provider.get_credentials()
            )
        except ValueError as error:
            raise OneDriveAuthError(MISSING_CREDENTIAL_CODE, str(error)) from error

    def _gateway(self) -> MicrosoftGraphGateway:
        if self._graph_gateway is not None:
            return self._graph_gateway
        credential = self._credentials()
        self._graph_gateway = MicrosoftGraphGateway(
            auth_config=MicrosoftGraphAuthConfig(
                client_id=credential.onedrive_client_id,
                directory_id=credential.onedrive_directory_id,
                authority_host=self._config(
                    CONFIG_AUTHORITY_HOST, DEFAULT_AUTHORITY_HOST
                ),
                auth_method=credential.onedrive_authentication_method,
                client_secret=credential.onedrive_client_secret,
                private_key_b64=credential.onedrive_private_key,
                certificate_password=credential.onedrive_certificate_password,
            ),
            graph_api_host=self._graph_host(),
            graph_api_version=GRAPH_API_VERSION,
        )
        return self._graph_gateway

    def _token_response(self) -> dict[str, Any]:
        return self._gateway().token_response()

    def _access_token(self) -> str:
        return self._gateway().access_token()

    def _client(self) -> GraphApiClient:
        return self._gateway().client

    def _get(self, url: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        return self._gateway().get_json(url, params)

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
    )
    def check_token(self) -> OneDriveTokenInfo:
        response = self._token_response()
        expires = response.get("expires_in")
        return OneDriveTokenInfo(
            expires_in=int(expires) if expires is not None else None
        )

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
    )
    def list_users(
        self, *, next_link: str | None = None, page_size: int = USERS_PAGE_SIZE
    ) -> OneDriveUserPage:
        params = None
        url = next_link
        if url is None:
            url = f"{self._base()}/users"
            params = {"$select": USER_SELECT, "$top": str(page_size)}
        data = self._get(url, params)
        users = [user for raw in data.get("value", []) if (user := _user(raw))]
        return OneDriveUserPage(users=users, next_link=data.get("@odata.nextLink"))

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.BOTH,
        untested=(
            "Configured-user checks exercise this only when connector config "
            "contains a user; the coverage spy has an empty config."
        ),
    )
    def get_user(self, *, identifier: str) -> OneDriveUser | None:
        try:
            raw = self._get(
                build_graph_user_url(self._base(), identifier),
                {"$select": USER_SELECT},
            )
        except OneDriveGraphError as error:
            if error.status == 404:
                return None
            raise
        return _user(raw)

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
        untested=(
            "The drive probe needs a user returned by Graph; the coverage spy "
            "has no tenant users."
        ),
    )
    def get_default_drive(self, *, user_id: str) -> OneDriveDrive | None:
        try:
            raw = self._get(f"{build_graph_user_url(self._base(), user_id)}/drive")
        except OneDriveGraphError as error:
            if error.status == 404:
                return None
            raise
        return OneDriveDrive(
            id=raw["id"], name=raw.get("name") or "OneDrive", web_url=raw.get("webUrl")
        )

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
        untested=(
            "The delta probe needs a drive returned by Graph; the coverage spy "
            "has no tenant users."
        ),
    )
    def get_delta_page(
        self, *, drive_id: str, page_url: str, page_size: int
    ) -> OneDriveDeltaResult:
        try:
            result = fetch_drive_delta_checkpoint_page(
                self._client(),
                page_url=page_url,
                drive_id=drive_id,
                request_headers=build_onedrive_delta_request_headers(),
                page_size=page_size,
                select_fields=DRIVE_DELTA_SELECT_FIELDS,
            )
        except (requests.RequestException, ValueError) as error:
            raise microsoft_error_from_exception(error) from error
        return OneDriveDeltaResult(
            page=result.page,
            next_cursor=result.next_checkpoint_url,
            resynced=result.resync_after_410,
        )

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
        untested=(
            "A safe download probe needs a file returned by delta; empty drives "
            "have no item that capability checks can read."
        ),
    )
    def download_item(
        self,
        *,
        item: DriveItemData,
        raw_file_callback: RawFileCallback | None = None,
    ) -> DriveItemContent | None:
        return extract_drive_item_content(
            item,
            SHAREPOINT_CONNECTOR_SIZE_THRESHOLD,
            self._base(),
            self._access_token(),
            raw_file_callback,
        )

    @source_operation(
        capabilities={CredentialCapability.DOC_PERMISSION_SYNC},
        consumes=OperationConsumes.CREDENTIAL,
        untested=(
            "Item permission reads need document context unavailable to "
            "credential checks."
        ),
    )
    def list_permissions(
        self, *, drive_id: str, item_id: str, next_link: str | None = None
    ) -> OneDrivePermissionPage:
        url = (
            next_link or f"{self._base()}/drives/{drive_id}/items/{item_id}/permissions"
        )
        data = self._get(url)
        return OneDrivePermissionPage(
            permissions=[
                OneDrivePermission.model_validate(raw) for raw in data.get("value", [])
            ],
            next_link=data.get("@odata.nextLink"),
        )

    @source_operation(
        capabilities={CredentialCapability.EXTERNAL_GROUP_SYNC},
        consumes=OperationConsumes.CREDENTIAL,
    )
    def list_groups(
        self, *, next_link: str | None = None, page_size: int = GROUPS_PAGE_SIZE
    ) -> OneDriveGroupPage:
        params = None
        url = next_link
        if url is None:
            url = f"{self._base()}/groups"
            params = {"$select": GROUP_SELECT, "$top": str(page_size)}
        data = self._get(url, params)
        return OneDriveGroupPage(
            groups=[OneDriveGroup.model_validate(raw) for raw in data.get("value", [])],
            next_link=data.get("@odata.nextLink"),
        )

    @source_operation(
        capabilities={CredentialCapability.EXTERNAL_GROUP_SYNC},
        consumes=OperationConsumes.CREDENTIAL,
        untested=(
            "Group expansion needs a concrete group id unavailable to "
            "credential checks."
        ),
    )
    def list_transitive_group_members(
        self, *, group_id: str, next_link: str | None = None
    ) -> OneDriveGroupMemberPage:
        params = None
        url = next_link
        if url is None:
            url = f"{self._base()}/groups/{quote(group_id)}/transitiveMembers"
            params = {"$select": GROUP_MEMBER_SELECT, "$top": str(GROUPS_PAGE_SIZE)}
        data = self._get(url, params)
        return OneDriveGroupMemberPage(
            members=[
                OneDriveGroupMember.model_validate(raw) for raw in data.get("value", [])
            ],
            next_link=data.get("@odata.nextLink"),
        )
