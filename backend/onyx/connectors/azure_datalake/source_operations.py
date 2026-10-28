"""Azure Data Lake Storage gateway: every Azure Storage call lives here.

The connector reads one container of one storage account through the DFS
endpoint. An app registration of the Microsoft credential family signs in with
MSAL for an Azure Storage token; an account key signs each request itself.
"""

import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any, ClassVar, TypeVar, cast

from azure.core.credentials import AccessToken
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
from pydantic import ValidationError

from onyx.configs.constants import DocumentSource
from onyx.connectors.azure_datalake.config import AzureDataLakeConnectorConfig
from onyx.connectors.azure_datalake.models import (
    AzureDataLakeAuthMethod,
    AzureDataLakeCredentials,
    AzureDataLakeFile,
    AzureDataLakePath,
    AzureDataLakePathPage,
    AzureDataLakeSignIn,
)
from onyx.connectors.capabilities import CredentialCapability
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialInvalidError,
    InsufficientPermissionsError,
    SourceApiError,
    UnreachableValidationError,
)
from onyx.connectors.microsoft_utils.config import DEFAULT_AUTHORITY_HOST
from onyx.connectors.microsoft_utils.graph_auth import (
    MicrosoftAuthContext,
    acquire_token_response,
    build_graph_auth_context,
    token_info,
)
from onyx.connectors.source_operations import (
    OperationConsumes,
    SourceOperations,
    source_operation,
)

STORAGE_RESOURCE = "https://storage.azure.com"
DFS_ENDPOINT_SUFFIX = "dfs.core.windows.net"
CONFIG_ACCOUNT_NAME = "account_name"
CONFIG_CONTAINER_NAME = "container_name"

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


class AzureDataLakeRequestError(SourceApiError):
    """Azure Storage answered with an error the gateway does not map."""


class _StorageTokenCredential:
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


class AzureDataLakeSourceOperations(SourceOperations):
    source = DocumentSource.AZURE_DATALAKE
    sdk_modules = ("azure",)
    config_keys = frozenset({CONFIG_ACCOUNT_NAME, CONFIG_CONTAINER_NAME})

    # Guards the lazy client build: the check runner calls one gateway from
    # several threads. Azure SDK clients are thread safe.
    _client_lock: ClassVar[threading.Lock] = threading.Lock()
    _service_cache: DataLakeServiceClient | None = None
    _file_system_cache: FileSystemClient | None = None

    def _config(self) -> AzureDataLakeConnectorConfig:
        try:
            return AzureDataLakeConnectorConfig.model_validate(
                self.connector_specific_config or {}
            )
        except ValidationError as e:
            raise ConnectorValidationError(
                "Set a valid storage account and container."
            ) from e

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
        return build_graph_auth_context(
            client_id=credentials.adls_client_id,
            directory_id=credentials.adls_directory_id,
            authority_host=DEFAULT_AUTHORITY_HOST,
            auth_method_value=credentials.authentication_method.value,
            client_secret=credentials.adls_client_secret,
            private_key_b64=credentials.adls_private_key,
            certificate_password=credentials.adls_certificate_password,
        )

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
                    if not credentials.adls_account_key:
                        raise CredentialInvalidError("The account key is missing.")
                    storage_credential: str | _StorageTokenCredential = (
                        credentials.adls_account_key
                    )
                else:
                    storage_credential = _StorageTokenCredential(
                        self._auth_context(credentials)
                    )
                self._service_cache = DataLakeServiceClient(
                    account_url=f"https://{self._config().account_name}.{DFS_ENDPOINT_SUFFIX}",
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
                f"'{self._config().account_name}'. Check the account name."
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
                raise ConnectorValidationError(
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
    def check_sign_in(self) -> AzureDataLakeSignIn:
        """An app registration gets an Azure Storage token. An account key
        signs one request for the account's first container."""
        credentials = self._credentials()
        if credentials.authentication_method is not AzureDataLakeAuthMethod.ACCOUNT_KEY:
            auth_context = self._auth_context(credentials)
            return AzureDataLakeSignIn(
                token=token_info(
                    auth_context, acquire_token_response(auth_context, STORAGE_RESOURCE)
                )
            )
        service = self._service()
        self._call(
            lambda: next(iter(service.list_file_systems(results_per_page=1)), None),
            "the storage account",
        )
        return AzureDataLakeSignIn(token=None)

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
            downloader = file_client.download_file()
            return AzureDataLakeFile(
                size=downloader.size,
                last_modified=_aware(downloader.properties.last_modified),
                content=downloader.readall() if downloader.size <= max_bytes else None,
            )

        return self._call(download, f"the file '{path}'")
