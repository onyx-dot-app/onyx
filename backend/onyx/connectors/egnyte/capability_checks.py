"""Named indexing checks for Egnyte, composed from the gateway's operations.

Indexing needs a token Egnyte accepts, a configured folder the token can list,
and files the token can download. Each check makes one or a few small calls,
because Egnyte allows a token about 1,000 calls a day.
"""

from collections.abc import Callable
from typing import TypeVar

from onyx.connectors.capability_checks.form_state import FormState
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CheckAdvisory,
    CheckOutput,
    CredentialCapability,
    form_config,
    sign_in_timeout_text,
)
from onyx.connectors.egnyte.config import EgnyteConnectorConfig
from onyx.connectors.egnyte.connector import is_indexable, normalize_folder_path
from onyx.connectors.egnyte.models import EgnyteFile
from onyx.connectors.egnyte.source_operations import (
    EgnyteApiError,
    EgnyteSourceOperations,
)
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    UnexpectedValidationError,
)

T = TypeVar("T")

SIGN_IN_CHECK_ID: str = "egnyte_token"
_FOLDER_CHECK_ID: str = "egnyte_folder"
_FILES_CHECK_ID: str = "egnyte_files"
# Folders listed while looking for a file to download.
_MAX_PROBE_FOLDERS: int = 5
_PROBE_PAGE_SIZE: int = 20
# Reading the start of a file proves read access without holding a large file.
_PROBE_BYTES: int = 64 * 1024


def gateway_from_context(context: CapabilityCheckContext) -> EgnyteSourceOperations:
    if not isinstance(context.source_operations, EgnyteSourceOperations):
        raise TypeError(
            "Bug: the runner constructs the registered gateway for migrated sources."
        )
    return context.source_operations


def configured_folder(context: CapabilityCheckContext) -> str:
    return normalize_folder_path(
        form_config(context, EgnyteConnectorConfig).folder_path
    )


def probe(action: Callable[[], T], denied: str) -> T:
    """Validation errors from the gateway already carry a user-facing message,
    so only other failures are wrapped. A missing folder names the folder."""
    try:
        return action()
    except EgnyteApiError as error:
        if error.status_code == 404:
            raise ConnectorValidationError(f"{denied} Egnyte found no such folder.")
        raise UnexpectedValidationError(f"{denied} {error}") from error


def find_sample_file(
    gateway: EgnyteSourceOperations, folder_path: str
) -> EgnyteFile | None:
    """The first file indexing would read, in a short breadth-first walk from
    the folder."""
    queue: list[str] = [folder_path]
    for _ in range(_MAX_PROBE_FOLDERS):
        if not queue:
            return None
        page = gateway.list_folder_page(
            folder_path=queue.pop(0), offset=0, page_size=_PROBE_PAGE_SIZE
        )
        sample = next((file for file in page.files if is_indexable(file)), None)
        if sample is not None:
            return sample
        queue.extend(folder.path for folder in page.folders)
    return None


class _SignInCheck(CapabilityCheck[EgnyteConnectorConfig]):
    config_class = EgnyteConnectorConfig

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id=SIGN_IN_CHECK_ID,
            display_name="Sign in to Egnyte",
            requires_connector_instance=False,
            validates_binding=True,
            fails_when_unreachable=True,
            timeout_text=sign_in_timeout_text("Egnyte"),
            remediation="Check the Egnyte domain, then connect the account again.",
        )

    def run(self, context: CapabilityCheckContext) -> None:
        probe(
            lambda: gateway_from_context(context).list_folder_page(
                folder_path="/", offset=0, page_size=1
            ),
            "Egnyte did not list the top folder.",
        )


class _FolderCheck(CapabilityCheck[EgnyteConnectorConfig]):
    config_class = EgnyteConnectorConfig

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id=_FOLDER_CHECK_ID,
            display_name="Find the folder",
            requires_connector_instance=False,
            requires_connector_config=True,
            depends_on=(SIGN_IN_CHECK_ID,),
            reports_field="folder_path",
            remediation=(
                "Check the folder path, e.g. /Shared/Documents, or give the "
                "connected user access to the folder."
            ),
        )

    def applies(self, form_state: FormState[EgnyteConnectorConfig]) -> bool:
        return bool(form_state.config.folder_path)

    def run(self, context: CapabilityCheckContext) -> None:
        folder_path: str = configured_folder(context)
        probe(
            lambda: gateway_from_context(context).list_folder_page(
                folder_path=folder_path, offset=0, page_size=1
            ),
            f"Onyx could not list {folder_path}.",
        )


class _FilesCheck(CapabilityCheck[EgnyteConnectorConfig]):
    config_class = EgnyteConnectorConfig

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id=_FILES_CHECK_ID,
            display_name="Files are readable",
            requires_connector_instance=False,
            requires_connector_config=True,
            depends_on=(SIGN_IN_CHECK_ID,),
            remediation="Give the connected user at least Viewer access to the folder.",
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput | None:
        gateway: EgnyteSourceOperations = gateway_from_context(context)
        folder_path: str = configured_folder(context)

        def download_sample() -> bool:
            """Whether a file was downloaded."""
            sample: EgnyteFile | None = find_sample_file(gateway, folder_path)
            if sample is None:
                return False
            # Failed files are read again by id.
            gateway.get_file(group_id=sample.group_id)
            gateway.download_file(group_id=sample.group_id, max_bytes=_PROBE_BYTES)
            return True

        if probe(download_sample, f"Onyx could not read files in {folder_path}."):
            return None
        return CheckOutput(
            advisories=[
                CheckAdvisory(
                    message="No file near the top of the folder, so downloads were not checked."
                )
            ]
        )


def build_egnyte_indexing_checks() -> list[CapabilityCheck]:
    return [_SignInCheck(), _FolderCheck(), _FilesCheck()]
