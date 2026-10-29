"""Named indexing checks for Azure Data Lake Storage, composed from the
gateway's operations.

Indexing needs a credential that signs in, a container it can list, the path
prefix inside it, and files it can read. An app registration gets this from
the Storage Blob Data Reader role; ACLs can grant it per directory instead.
"""

from collections.abc import Callable
from typing import TypeVar

from onyx.configs.app_configs import BLOB_STORAGE_SIZE_THRESHOLD
from onyx.connectors.azure_datalake.config import AzureDataLakeConnectorConfig
from onyx.connectors.azure_datalake.connector import is_indexable_file
from onyx.connectors.azure_datalake.models import AzureDataLakePath
from onyx.connectors.azure_datalake.source_operations import (
    AzureDataLakeRequestError,
    AzureDataLakeSourceOperations,
)
from onyx.connectors.capability_checks.form_state import FormState
from onyx.connectors.capability_checks.microsoft_check_text import (
    raise_for_sign_in_error,
    sign_in_text,
)
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CheckAdvisory,
    CheckOutput,
    CredentialCapability,
    MicrosoftSignIn,
    sign_in_timeout_text,
)
from onyx.connectors.exceptions import (
    InsufficientPermissionsError,
    UnexpectedValidationError,
)
from onyx.connectors.microsoft_utils.graph_errors import (
    MicrosoftAuthError,
    MicrosoftGraphError,
    raise_for_auth_error,
)
from onyx.connectors.microsoft_utils.models import (
    MicrosoftAccountLabels,
    MicrosoftTokenInfo,
)

T = TypeVar("T")

SIGN_IN_CHECK_ID = "adls_sign_in"
CONTAINER_CHECK_ID = "adls_container"
PATH_PREFIX_CHECK_ID = "adls_path_prefix"
FILE_READ_CHECK_ID = "adls_file_read"

_DOCS_LINK = "https://docs.onyx.app/admins/connectors/official/azure_datalake"
_ACCOUNT_LABELS = MicrosoftAccountLabels.with_prefix(
    "Azure Data Lake", private_key="Azure Data Lake Certificate"
)
_ACCOUNT_FIELDS = frozenset({"account_name"})
_CONTAINER_FIELDS = frozenset({"account_name", "container_name"})
_ALL_FIELDS = frozenset({"account_name", "container_name", "path_prefix"})
# The file check reads the smallest file among this many listed paths.
_FILE_PROBE_PAGE_SIZE = 100
_FILE_PROBE_MAX_PAGES = 5
_ROLE_REMEDIATION = (
    "Give the app registration the Storage Blob Data Reader role on the "
    "container, or read and execute ACL access to the files."
)


def _gateway(context: CapabilityCheckContext) -> AzureDataLakeSourceOperations:
    if not isinstance(context.source_operations, AzureDataLakeSourceOperations):
        raise TypeError(
            "Bug: the runner constructs the registered gateway for migrated sources."
        )
    return context.source_operations


def _probe(action: Callable[[], T], failed: str) -> T:
    """Validation errors from the gateway already carry a user-facing message,
    so only unmapped storage errors are wrapped."""
    try:
        return action()
    except AzureDataLakeRequestError as error:
        raise UnexpectedValidationError(f"{failed} {error}") from error


def _sign_in(gateway: AzureDataLakeSourceOperations) -> MicrosoftTokenInfo | None:
    try:
        return gateway.check_sign_in()
    except MicrosoftAuthError as error:
        raise_for_auth_error(error, _ACCOUNT_LABELS)
    except MicrosoftGraphError as error:
        raise_for_sign_in_error(error)


def _smallest_file(
    gateway: AzureDataLakeSourceOperations, path_prefix: str
) -> AzureDataLakePath | None:
    """The smallest non-empty file in the first few listing pages that
    indexing admits. Images are left out: the check cannot read the image
    setting."""
    files: list[AzureDataLakePath] = []
    continuation_token: str | None = None
    for _ in range(_FILE_PROBE_MAX_PAGES):
        page = gateway.list_paths_page(
            path_prefix=path_prefix,
            recursive=True,
            page_size=_FILE_PROBE_PAGE_SIZE,
            continuation_token=continuation_token,
        )
        files.extend(
            path
            for path in page.paths
            if path.content_length > 0
            and is_indexable_file(
                path, allow_images=False, size_threshold=BLOB_STORAGE_SIZE_THRESHOLD
            )
        )
        continuation_token = page.continuation_token
        if files or continuation_token is None:
            break
    if not files:
        return None
    return min(files, key=lambda path: path.content_length)


class _AzureDataLakeCheck(CapabilityCheck[AzureDataLakeConnectorConfig]):
    config_class = AzureDataLakeConnectorConfig

    def __init__(
        self,
        *,
        check_id: str,
        display_name: str,
        remediation: str,
        requires_fields: frozenset[str],
        config_fields: frozenset[str],
        depends_on: tuple[str, ...] = (),
        validates_binding: bool = False,
        fails_when_unreachable: bool = False,
    ) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id=check_id,
            display_name=display_name,
            requires_connector_instance=False,
            requires_fields=requires_fields,
            config_fields=config_fields,
            remediation=remediation,
            docs_link=_DOCS_LINK,
            depends_on=depends_on,
            validates_binding=validates_binding,
            fails_when_unreachable=fails_when_unreachable,
            timeout_text=sign_in_timeout_text("Azure Storage"),
        )


class _SignInCheck(_AzureDataLakeCheck):
    def __init__(self) -> None:
        super().__init__(
            check_id=SIGN_IN_CHECK_ID,
            display_name="Sign in to Azure Storage",
            remediation=(
                "Check the app id, tenant id and client credential, or the "
                "storage account name and account key."
            ),
            requires_fields=_ACCOUNT_FIELDS,
            config_fields=_ACCOUNT_FIELDS,
            validates_binding=True,
            fails_when_unreachable=True,
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        token: MicrosoftTokenInfo | None = _probe(
            lambda: _sign_in(_gateway(context)), "The sign-in could not be checked."
        )
        if token is None:
            return CheckOutput(summary="Signed in with the account key")
        text: MicrosoftSignIn = sign_in_text(token, _ACCOUNT_LABELS)
        return CheckOutput(
            summary=text.summary,
            description=text.description,
            advisories=[CheckAdvisory(message=caveat) for caveat in text.caveats],
        )


class _ContainerCheck(_AzureDataLakeCheck):
    def __init__(self) -> None:
        super().__init__(
            check_id=CONTAINER_CHECK_ID,
            display_name="The container is readable",
            remediation=f"Check the container name. {_ROLE_REMEDIATION}",
            requires_fields=_CONTAINER_FIELDS,
            config_fields=_ALL_FIELDS,
            depends_on=(SIGN_IN_CHECK_ID,),
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput | None:
        gateway = _gateway(context)
        try:
            _probe(
                lambda: gateway.list_paths_page(
                    path_prefix="",
                    recursive=False,
                    page_size=1,
                    continuation_token=None,
                ),
                "The container could not be listed.",
            )
        except InsufficientPermissionsError:
            # ACL access can start below the root: execute on the root and
            # read on the path prefix. The path prefix check lists that.
            if not self.config(context).path_prefix:
                raise
            return CheckOutput(
                advisories=[
                    CheckAdvisory(
                        message=(
                            "The container root is not readable, so only the "
                            "path prefix is checked."
                        )
                    )
                ]
            )
        return None


class _PathPrefixCheck(_AzureDataLakeCheck):
    def __init__(self) -> None:
        super().__init__(
            check_id=PATH_PREFIX_CHECK_ID,
            display_name="The path prefix exists",
            remediation="Check the path prefix: a directory in the container.",
            requires_fields=_CONTAINER_FIELDS,
            config_fields=_ALL_FIELDS,
            depends_on=(CONTAINER_CHECK_ID,),
        )

    def applies(self, form_state: FormState[AzureDataLakeConnectorConfig]) -> bool:
        return bool(form_state.config.path_prefix)

    def run(self, context: CapabilityCheckContext) -> None:
        gateway = _gateway(context)
        path_prefix: str = self.config(context).path_prefix
        _probe(
            lambda: gateway.list_paths_page(
                path_prefix=path_prefix,
                recursive=False,
                page_size=1,
                continuation_token=None,
            ),
            "The path prefix could not be listed.",
        )


class _FileReadCheck(_AzureDataLakeCheck):
    def __init__(self) -> None:
        super().__init__(
            check_id=FILE_READ_CHECK_ID,
            display_name="Files are readable",
            remediation=_ROLE_REMEDIATION,
            requires_fields=_CONTAINER_FIELDS,
            config_fields=_ALL_FIELDS,
            depends_on=(CONTAINER_CHECK_ID,),
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput | None:
        gateway = _gateway(context)
        path_prefix: str = self.config(context).path_prefix
        file: AzureDataLakePath | None = _probe(
            lambda: _smallest_file(gateway, path_prefix),
            "The files could not be listed.",
        )
        if file is None:
            return CheckOutput(
                advisories=[
                    CheckAdvisory(
                        message="No file in scope to read, so read access was not checked."
                    )
                ]
            )
        _probe(
            lambda: gateway.read_file(path=file.name, max_bytes=0),
            f"The file {file.name} could not be read.",
        )
        return None


def build_azure_datalake_indexing_checks() -> list[CapabilityCheck]:
    return [_SignInCheck(), _ContainerCheck(), _PathPrefixCheck(), _FileReadCheck()]
