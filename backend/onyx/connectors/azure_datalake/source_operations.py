"""Azure Data Lake Storage gateway: every Azure Storage call lives here.

The connector reads one container of one storage account through the DFS
endpoint. An app registration of the Microsoft credential family signs in with
MSAL for an Azure Storage token; an account key signs each request itself.

Permission sync also reads the account's role assignments from Azure Resource
Manager and the tenant's users and groups from Microsoft Graph, both with the
same app registration.
"""

import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any, ClassVar, TypeVar, cast
from urllib.parse import quote

import requests
from azure.core.credentials import AccessToken, TokenCredential
from azure.core.exceptions import (
    ClientAuthenticationError,
    HttpResponseError,
    ServiceRequestError,
)
from azure.core.paging import PageIterator
from azure.storage.filedatalake import (
    DataLakeServiceClient,
    FileSystemClient,
    PathProperties,
)
from pydantic import Field, ValidationError

from onyx.configs.constants import DocumentSource
from onyx.connectors.azure_datalake.config import (
    AzureDataLakeConnectorConfig,
    AzureDataLakeCredentialBinding,
)
from onyx.connectors.azure_datalake.models import (
    ArmModel,
    AzureDataLakeAccessControl,
    AzureDataLakeAuthMethod,
    AzureDataLakeContainerAccess,
    AzureDataLakeCredentials,
    AzureDataLakeFile,
    AzureDataLakePath,
    AzureDataLakePathPage,
    AzureDenyAssignment,
    AzureRoleAssignment,
    AzureRoleDefinition,
    AzureStorageAccountPage,
    AzureSubscriptionPage,
)
from onyx.connectors.capabilities import CredentialCapability
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialInvalidError,
    InsufficientPermissionsError,
    SourceApiError,
    UnreachableValidationError,
)
from onyx.connectors.microsoft_utils.config import (
    DEFAULT_AUTHORITY_HOST,
    DEFAULT_GRAPH_API_HOST,
)
from onyx.connectors.microsoft_utils.entra import (
    ENTRA_GROUP_MEMBER_SELECT,
    ENTRA_GROUP_SELECT,
    ENTRA_PAGE_SIZE,
    ENTRA_USER_SELECT,
    EntraDirectoryObject,
    EntraGroup,
    EntraPage,
    EntraUser,
    fetch_entra_page,
)
from onyx.connectors.microsoft_utils.graph_auth import (
    MicrosoftAuthContext,
    acquire_token_response,
    build_graph_auth_context,
    token_info,
)
from onyx.connectors.microsoft_utils.graph_client import graph_api_get_json
from onyx.connectors.microsoft_utils.models import MicrosoftTokenInfo
from onyx.connectors.source_operations import (
    OperationConsumes,
    SourceOperations,
    source_operation,
)

STORAGE_RESOURCE = "https://storage.azure.com"
DFS_ENDPOINT_SUFFIX = "dfs.core.windows.net"
CONFIG_ACCOUNT_NAME = "account_name"
CONFIG_CONTAINER_NAME = "container_name"

ARM_RESOURCE = "https://management.azure.com"
GRAPH_API_VERSION = "v1.0"
_SUBSCRIPTIONS_API_VERSION = "2022-12-01"
_STORAGE_API_VERSION = "2023-05-01"
_AUTHORIZATION_API_VERSION = "2022-04-01"
# Role and deny assignments at a scope and every scope above it.
_AT_SCOPE_FILTER = "atScope()"
# A listing still paging past this is a cursor that does not advance.
_MAX_ARM_PAGES = 1_000
_UNAUTHORIZED_STATUS = 401

_CONNECTION_TIMEOUT_SECONDS = 20
_READ_TIMEOUT_SECONDS = 120
_RETRY_TOTAL = 5
# The first request of a download reads at most this much, so a file larger
# than the caller's limit costs one small read before it is skipped.
_FIRST_GET_BYTES = 4 * 1024 * 1024
_FORBIDDEN_STATUS = 403
_NOT_FOUND_STATUS = 404
_CONTAINER_NOT_FOUND_CODES = frozenset({"ContainerNotFound", "FilesystemNotFound"})

T = TypeVar("T")
ArmModelT = TypeVar("ArmModelT", bound=ArmModel)


class AzureDataLakeRequestError(SourceApiError):
    """Azure Storage answered with an error the gateway does not map."""


class AzureDataLakeNotFoundError(ConnectorValidationError):
    """The path, or the Azure Resource Manager or Microsoft Graph object, does
    not exist, e.g. a file deleted after the listing or a group deleted after
    an ACL named it."""


class _StorageTokenCredential(TokenCredential):
    """An azure-core token credential backed by the family's MSAL client.
    MSAL caches the token until shortly before it expires."""

    def __init__(self, auth_context: MicrosoftAuthContext) -> None:
        self._auth_context = auth_context

    def get_token(
        self,
        *scopes: str,  # noqa: ARG002
        claims: str | None = None,  # noqa: ARG002
        tenant_id: str | None = None,  # noqa: ARG002
        enable_cae: bool = False,  # noqa: ARG002
        **kwargs: Any,  # noqa: ARG002
    ) -> AccessToken:
        """The storage client asks only for the Azure Storage scope."""
        response: dict[str, Any] = acquire_token_response(
            self._auth_context, STORAGE_RESOURCE
        )
        return AccessToken(
            str(response["access_token"]),
            int(time.time()) + int(response["expires_in"]),
        )


def _error_code(error: HttpResponseError) -> str | None:
    # azure-storage sets ``error_code`` on the instance; azure-core declares no
    # such attribute.
    return getattr(error, "error_code", None)  # ods: ignore[getattr]


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _path(properties: PathProperties) -> AzureDataLakePath:
    return AzureDataLakePath(
        name=properties.name,
        is_directory=bool(properties.is_directory),
        last_modified=_aware(properties.last_modified),
        content_length=properties.content_length or 0,
    )


class _ArmListPage(ArmModel):
    # Each item is parsed into the caller's model.
    value: list[dict[str, Any]] = Field(default_factory=list)
    next_link: str | None = None


def _parse_arm(model: type[ArmModelT], data: Any, url: str, target: str) -> ArmModelT:
    """``data`` as ``model``. A response without a field the model needs
    raises, so missing data never reads as an empty value."""
    try:
        return model.model_validate(data)
    except ValidationError as e:
        raise AzureDataLakeRequestError(
            f"Azure Resource Manager returned {target} in an unknown shape.",
            status_code=None,
            method="GET",
            url=url,
        ) from e


class AzureDataLakeSourceOperations(SourceOperations):
    source = DocumentSource.AZURE_DATALAKE
    sdk_modules = ("azure", "requests")
    config_keys = frozenset({CONFIG_ACCOUNT_NAME, CONFIG_CONTAINER_NAME})

    # Guards the lazy client builds: the check runner calls one gateway from
    # several threads. Azure SDK clients are thread safe. Reentrant, since the
    # storage client build signs in through the cached MSAL client.
    _client_lock: ClassVar[threading.RLock] = threading.RLock()
    _service_cache: DataLakeServiceClient | None = None
    _file_system_cache: FileSystemClient | None = None
    _auth_context_cache: MicrosoftAuthContext | None = None

    def _config(self) -> AzureDataLakeConnectorConfig:
        try:
            return AzureDataLakeConnectorConfig.model_validate(
                self.connector_specific_config or {}
            )
        except ValidationError as e:
            raise ConnectorValidationError(
                "Set a valid storage account and container."
            ) from e

    def _account_name(self) -> str:
        """The storage account alone, which the account-level client and the
        sign-in check need before a container is chosen."""
        try:
            return AzureDataLakeCredentialBinding.model_validate(
                self.connector_specific_config or {}
            ).account_name
        except ValidationError as e:
            raise ConnectorValidationError("Set a valid storage account.") from e

    def _credentials(self) -> AzureDataLakeCredentials:
        try:
            return AzureDataLakeCredentials.model_validate(
                self.credentials_provider.get_credentials()
            )
        except ValidationError as e:
            raise CredentialInvalidError(
                "The credential is not an Azure Data Lake credential."
            ) from e

    def _auth_context(
        self, credentials: AzureDataLakeCredentials
    ) -> MicrosoftAuthContext:
        """One MSAL client per gateway, so its token cache serves every
        resource the app signs in to."""
        if self._auth_context_cache is not None:
            return self._auth_context_cache
        with self._client_lock:
            if self._auth_context_cache is None:
                self._auth_context_cache = build_graph_auth_context(
                    client_id=credentials.adls_client_id,
                    directory_id=credentials.adls_directory_id,
                    authority_host=DEFAULT_AUTHORITY_HOST,
                    auth_method_value=credentials.authentication_method.value,
                    client_secret=credentials.adls_client_secret,
                    private_key_b64=credentials.adls_private_key,
                    certificate_password=credentials.adls_certificate_password,
                )
        return self._auth_context_cache

    def _app_auth_context(self) -> MicrosoftAuthContext:
        """The app registration's sign-in. An account key opens storage only,
        so it cannot read role assignments or the directory."""
        if self._auth_context_cache is not None:
            return self._auth_context_cache
        credentials = self._credentials()
        if credentials.authentication_method is AzureDataLakeAuthMethod.ACCOUNT_KEY:
            raise CredentialInvalidError(
                "An account key cannot read role assignments or Entra users and "
                "groups. Use an app registration for permission sync."
            )
        return self._auth_context(credentials)

    def _get_json(
        self,
        resource: str,
        url: str,
        params: dict[str, str] | None,
        target: str,
    ) -> dict[str, Any]:
        """One authenticated GET to Azure Resource Manager or Microsoft Graph,
        with the Graph transport's retries. ``target`` names what was
        requested, for the message."""
        auth_context = self._app_auth_context()

        def access_token() -> str:
            return str(acquire_token_response(auth_context, resource)["access_token"])

        try:
            return graph_api_get_json(access_token, url, params)
        except requests.HTTPError as e:
            status: int | None = (
                e.response.status_code if e.response is not None else None
            )
            body: str | None = (
                e.response.text[:2000] if e.response is not None else None
            )
            if status == _UNAUTHORIZED_STATUS:
                raise CredentialInvalidError(
                    f"Microsoft rejected the app's token for {target}."
                ) from e
            if status == _FORBIDDEN_STATUS:
                raise InsufficientPermissionsError(
                    f"The app registration cannot read {target}."
                ) from e
            if status == _NOT_FOUND_STATUS:
                raise AzureDataLakeNotFoundError(f"{target} does not exist.") from e
            raise AzureDataLakeRequestError(
                f"Microsoft failed on {target} ({status}).",
                status_code=status,
                method="GET",
                url=url,
                body=body,
            ) from e
        except (requests.RequestException, ValueError) as e:
            raise UnreachableValidationError(
                f"Onyx cannot read {target} from Microsoft: {e}"
            ) from e

    def _arm_get(
        self, url: str, params: dict[str, str] | None, target: str
    ) -> dict[str, Any]:
        return self._get_json(ARM_RESOURCE, url, params, target)

    def _arm_model(
        self,
        model: type[ArmModelT],
        url: str,
        params: dict[str, str] | None,
        target: str,
    ) -> ArmModelT:
        """One ARM GET, parsed into ``model``. A response without a field
        the model needs raises."""
        return _parse_arm(model, self._arm_get(url, params, target), url, target)

    def _arm_list(
        self,
        item_model: type[ArmModelT],
        url: str,
        params: dict[str, str],
        target: str,
    ) -> list[ArmModelT]:
        """Every item of an ARM collection, following ``nextLink``."""
        items: list[ArmModelT] = []
        next_link: str | None = None
        for _ in range(_MAX_ARM_PAGES):
            page_url: str = next_link or url
            page: _ArmListPage = self._arm_model(
                _ArmListPage, page_url, None if next_link else params, target
            )
            items.extend(
                _parse_arm(item_model, raw, page_url, target) for raw in page.value
            )
            next_link = page.next_link
            if not next_link:
                return items
        raise RuntimeError(f"{target} passed {_MAX_ARM_PAGES} pages")

    def _graph_get(
        self, url: str, params: dict[str, str] | None, target: str
    ) -> dict[str, Any]:
        return self._get_json(DEFAULT_GRAPH_API_HOST, url, params, target)

    def _graph_base(self) -> str:
        return f"{DEFAULT_GRAPH_API_HOST}/{GRAPH_API_VERSION}"

    def _service(self) -> DataLakeServiceClient:
        if self._service_cache is not None:
            return self._service_cache
        with self._client_lock:
            if self._service_cache is None:
                credentials = self._credentials()
                if (
                    credentials.authentication_method
                    is AzureDataLakeAuthMethod.ACCOUNT_KEY
                ):
                    if credentials.adls_account_key is None:
                        raise CredentialInvalidError("The account key is missing.")
                    storage_credential: str | _StorageTokenCredential = (
                        credentials.adls_account_key
                    )
                else:
                    storage_credential = _StorageTokenCredential(
                        self._auth_context(credentials)
                    )
                self._service_cache = DataLakeServiceClient(
                    account_url=f"https://{self._account_name()}.{DFS_ENDPOINT_SUFFIX}",
                    credential=storage_credential,
                    connection_timeout=_CONNECTION_TIMEOUT_SECONDS,
                    read_timeout=_READ_TIMEOUT_SECONDS,
                    retry_total=_RETRY_TOTAL,
                    max_single_get_size=_FIRST_GET_BYTES,
                    max_chunk_get_size=_FIRST_GET_BYTES,
                )
        return self._service_cache

    def _file_system(self) -> FileSystemClient:
        if self._file_system_cache is None:
            self._file_system_cache = self._service().get_file_system_client(
                self._config().container_name
            )
        return self._file_system_cache

    def _call(self, action: Callable[[], T], target: str) -> T:
        """Runs one storage request and maps its failure. ``target`` names
        what was requested, for the message."""
        try:
            return action()
        except ClientAuthenticationError as e:
            raise CredentialInvalidError(
                f"Azure Storage rejected the credential ({_error_code(e)})."
            ) from e
        except ServiceRequestError as e:
            raise UnreachableValidationError(
                f"Onyx cannot reach the storage account "
                f"'{self._account_name()}'. Check the account name."
            ) from e
        except HttpResponseError as e:
            code: str | None = _error_code(e)
            if e.status_code == _FORBIDDEN_STATUS:
                raise InsufficientPermissionsError(
                    f"The credential cannot read {target} ({code}). Give it the "
                    "Storage Blob Data Reader role, or read and execute ACL access."
                ) from e
            if e.status_code == _NOT_FOUND_STATUS:
                config = self._config()
                if code in _CONTAINER_NOT_FOUND_CODES:
                    raise ConnectorValidationError(
                        f"The container '{config.container_name}' does not exist in "
                        f"the storage account '{config.account_name}'."
                    ) from e
                raise AzureDataLakeNotFoundError(
                    f"{target} does not exist ({code})."
                ) from e
            raise AzureDataLakeRequestError(
                f"Azure Storage failed on {target} ({code}): {e.reason}",
                status_code=e.status_code,
            ) from e

    @source_operation(
        capabilities=(CredentialCapability.INDEXING,),
        consumes=OperationConsumes.BOTH,
    )
    def check_sign_in(self) -> MicrosoftTokenInfo | None:
        """An app registration gets an Azure Storage token. An account key,
        which has no token, signs one request for the account's first
        container."""
        credentials = self._credentials()
        if credentials.authentication_method is not AzureDataLakeAuthMethod.ACCOUNT_KEY:
            auth_context = self._auth_context(credentials)
            return token_info(
                auth_context, acquire_token_response(auth_context, STORAGE_RESOURCE)
            )
        service = self._service()
        self._call(
            lambda: next(iter(service.list_file_systems(results_per_page=1)), None),
            "the storage account",
        )
        return None

    @source_operation(
        capabilities=(CredentialCapability.INDEXING,),
        consumes=OperationConsumes.BOTH,
    )
    def list_paths_page(
        self,
        *,
        path_prefix: str,
        recursive: bool,
        page_size: int,
        continuation_token: str | None,
    ) -> AzureDataLakePathPage:
        """One page of the paths under ``path_prefix``, parents before children."""
        file_system = self._file_system()

        def read_page() -> AzureDataLakePathPage:
            # by_page is typed as a plain iterator; it returns a PageIterator,
            # which holds the next page's cursor.
            pager = cast(
                PageIterator[PathProperties],
                file_system.get_paths(
                    path=path_prefix or None, recursive=recursive, max_results=page_size
                ).by_page(continuation_token=continuation_token),
            )
            page = next(pager, None)
            if continuation_token and pager.continuation_token == continuation_token:
                raise RuntimeError(
                    "Azure Storage returned the same listing cursor again."
                )
            return AzureDataLakePathPage(
                paths=[_path(properties) for properties in page or []],
                continuation_token=pager.continuation_token,
            )

        return self._call(read_page, f"the path '{path_prefix or '/'}'")

    @source_operation(
        capabilities=(CredentialCapability.INDEXING,),
        consumes=OperationConsumes.BOTH,
    )
    def read_file(self, *, path: str, max_bytes: int) -> AzureDataLakeFile:
        """The file's content, or None for it when the file is larger than
        ``max_bytes``."""
        file_client = self._file_system().get_file_client(path)

        def download() -> AzureDataLakeFile:
            # Stored bytes only: decompressing a gzip-encoded file would expand
            # it in memory before the size check.
            downloader = file_client.download_file(decompress=False)
            return AzureDataLakeFile(
                size=downloader.size,
                last_modified=_aware(downloader.properties.last_modified),
                content=downloader.readall() if downloader.size <= max_bytes else None,
            )

        return self._call(download, f"the file '{path}'")

    @source_operation(
        capabilities=(CredentialCapability.DOC_PERMISSION_SYNC,),
        consumes=OperationConsumes.BOTH,
    )
    def get_access_control(
        self, *, path: str, is_directory: bool
    ) -> AzureDataLakeAccessControl:
        """The path's owner, owning group and ACL, principals as object ids.
        An empty ``path`` is the container's root directory."""
        file_system = self._file_system()

        def read() -> AzureDataLakeAccessControl:
            client = (
                file_system.get_directory_client(path or "/")
                if is_directory or not path
                else file_system.get_file_client(path)
            )
            headers: dict[str, Any] = client.get_access_control(upn=False)
            return AzureDataLakeAccessControl(
                owner=str(headers.get("owner") or ""),
                group=str(headers.get("group") or ""),
                permissions=str(headers.get("permissions") or ""),
                acl=str(headers.get("acl") or ""),
            )

        return self._call(read, f"the access control of '{path or '/'}'")

    @source_operation(
        capabilities=(CredentialCapability.DOC_PERMISSION_SYNC,),
        consumes=OperationConsumes.BOTH,
    )
    def get_container_access(self) -> AzureDataLakeContainerAccess:
        """Whether the container lets anonymous clients read its files."""
        file_system = self._file_system()

        def read() -> AzureDataLakeContainerAccess:
            properties = file_system.get_file_system_properties()
            return AzureDataLakeContainerAccess(
                anonymous_read=properties.public_access is not None
            )

        return self._call(read, "the container's anonymous access level")

    @source_operation(
        capabilities=(CredentialCapability.DOC_PERMISSION_SYNC,),
        consumes=OperationConsumes.CREDENTIAL,
    )
    def list_subscriptions(
        self, *, next_link: str | None = None
    ) -> AzureSubscriptionPage:
        """The subscriptions where the app holds a role."""
        return self._arm_model(
            AzureSubscriptionPage,
            next_link or f"{ARM_RESOURCE}/subscriptions",
            None if next_link else {"api-version": _SUBSCRIPTIONS_API_VERSION},
            "the Azure subscriptions",
        )

    @source_operation(
        capabilities=(CredentialCapability.DOC_PERMISSION_SYNC,),
        consumes=OperationConsumes.CREDENTIAL,
    )
    def list_storage_accounts(
        self, *, subscription_id: str, next_link: str | None = None
    ) -> AzureStorageAccountPage:
        """The storage accounts of one subscription that the app can read."""
        return self._arm_model(
            AzureStorageAccountPage,
            next_link
            or (
                f"{ARM_RESOURCE}/subscriptions/{quote(subscription_id)}"
                "/providers/Microsoft.Storage/storageAccounts"
            ),
            None if next_link else {"api-version": _STORAGE_API_VERSION},
            f"the storage accounts of subscription {subscription_id}",
        )

    @source_operation(
        capabilities=(CredentialCapability.DOC_PERMISSION_SYNC,),
        consumes=OperationConsumes.CREDENTIAL,
    )
    def list_role_assignments(self, *, scope: str) -> list[AzureRoleAssignment]:
        """The role assignments at ``scope`` (an ARM resource id) and above."""
        return self._arm_list(
            AzureRoleAssignment,
            f"{ARM_RESOURCE}{scope}/providers/Microsoft.Authorization/roleAssignments",
            {"api-version": _AUTHORIZATION_API_VERSION, "$filter": _AT_SCOPE_FILTER},
            "the role assignments of the container",
        )

    @source_operation(
        capabilities=(CredentialCapability.DOC_PERMISSION_SYNC,),
        consumes=OperationConsumes.CREDENTIAL,
    )
    def get_role_definition(self, *, role_definition_id: str) -> AzureRoleDefinition:
        """A role's actions and data actions. ``role_definition_id`` is the
        ARM id a role assignment names."""
        return self._arm_model(
            AzureRoleDefinition,
            f"{ARM_RESOURCE}{role_definition_id}",
            {"api-version": _AUTHORIZATION_API_VERSION},
            f"the role definition {role_definition_id}",
        )

    @source_operation(
        capabilities=(CredentialCapability.DOC_PERMISSION_SYNC,),
        consumes=OperationConsumes.CREDENTIAL,
    )
    def list_deny_assignments(self, *, scope: str) -> list[AzureDenyAssignment]:
        """The deny assignments at ``scope`` (an ARM resource id) and above."""
        return self._arm_list(
            AzureDenyAssignment,
            f"{ARM_RESOURCE}{scope}/providers/Microsoft.Authorization/denyAssignments",
            {"api-version": _AUTHORIZATION_API_VERSION, "$filter": _AT_SCOPE_FILTER},
            "the deny assignments of the container",
        )

    @source_operation(
        capabilities=(
            CredentialCapability.DOC_PERMISSION_SYNC,
            CredentialCapability.EXTERNAL_GROUP_SYNC,
        ),
        consumes=OperationConsumes.CREDENTIAL,
    )
    def list_users(
        self, *, next_link: str | None = None, page_size: int = ENTRA_PAGE_SIZE
    ) -> EntraPage[EntraUser]:
        """One page of the tenant's users, members and guests."""
        return fetch_entra_page(
            lambda url, params: self._graph_get(url, params, "the Entra users"),
            url=f"{self._graph_base()}/users",
            item_model=EntraUser,
            select_fields=ENTRA_USER_SELECT,
            next_link=next_link,
            page_size=page_size,
        )

    @source_operation(
        capabilities=(CredentialCapability.EXTERNAL_GROUP_SYNC,),
        consumes=OperationConsumes.CREDENTIAL,
    )
    def list_groups(
        self, *, next_link: str | None = None, page_size: int = ENTRA_PAGE_SIZE
    ) -> EntraPage[EntraGroup]:
        """One page of the tenant's groups."""
        return fetch_entra_page(
            lambda url, params: self._graph_get(url, params, "the Entra groups"),
            url=f"{self._graph_base()}/groups",
            item_model=EntraGroup,
            select_fields=ENTRA_GROUP_SELECT,
            next_link=next_link,
            page_size=page_size,
        )

    @source_operation(
        capabilities=(
            CredentialCapability.DOC_PERMISSION_SYNC,
            CredentialCapability.EXTERNAL_GROUP_SYNC,
        ),
        consumes=OperationConsumes.CREDENTIAL,
    )
    def list_transitive_group_members(
        self, *, group_id: str, next_link: str | None = None
    ) -> EntraPage[EntraDirectoryObject]:
        """One page of a group's members, nested groups' members included."""
        return fetch_entra_page(
            lambda url, params: self._graph_get(
                url, params, f"the members of the Entra group {group_id}"
            ),
            url=f"{self._graph_base()}/groups/{quote(group_id)}/transitiveMembers",
            item_model=EntraDirectoryObject,
            select_fields=ENTRA_GROUP_MEMBER_SELECT,
            next_link=next_link,
        )
