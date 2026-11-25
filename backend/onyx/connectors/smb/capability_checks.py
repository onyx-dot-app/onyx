"""Named indexing checks for a Windows file share, composed from the gateway's
operations.

Indexing needs a file server that answers on the SMB port, a service account
that signs in, a signed session, a share the account can list, the path prefix
inside it, and files the account can read.
"""

import ipaddress
from collections.abc import Callable
from typing import TypeVar

from onyx.configs.app_configs import BLOB_STORAGE_SIZE_THRESHOLD
from onyx.connectors.capability_checks.form_state import FormState
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CheckAdvisory,
    CheckNotApplicableError,
    CheckOutput,
    CredentialCapability,
    sign_in_timeout_text,
)
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    InsufficientPermissionsError,
    UnexpectedValidationError,
)
from onyx.connectors.smb.config import SmbConnectorConfig
from onyx.connectors.smb.connector import (
    is_indexable_file,
    is_skipped_entry,
    join_path,
)
from onyx.connectors.smb.models import (
    KerberosTicket,
    SmbAuthMethod,
    SmbCredentials,
    SmbEntry,
    SmbSessionInfo,
)
from onyx.connectors.smb.source_operations import (
    SmbRequestError,
    SmbSourceOperations,
)

T = TypeVar("T")

REACHABLE_CHECK_ID = "smb_reachable"
KERBEROS_TICKET_CHECK_ID = "smb_kerberos_ticket"
SIGN_IN_CHECK_ID = "smb_sign_in"
TRANSPORT_CHECK_ID = "smb_transport"
SHARE_CHECK_ID = "smb_share"
PATH_PREFIX_CHECK_ID = "smb_path_prefix"
FILE_READ_CHECK_ID = "smb_file_read"

DOCS_LINK = "https://docs.onyx.app/admins/connectors/official/smb"
SERVER_FIELDS = frozenset({"host", "port"})
HOST_FIELDS = frozenset({"host"})
SESSION_FIELDS = frozenset({"host", "port", "require_encryption"})
SHARE_REQUIRED_FIELDS = frozenset({"host", "share"})
SHARE_FIELDS = SESSION_FIELDS | {"share"}
SCOPE_FIELDS = SHARE_FIELDS | {"path_prefix", "excluded_paths", "index_offline_files"}
# The file check looks for a file in this many folders, widest first.
FILE_PROBE_MAX_FOLDERS = 20
_READ_REMEDIATION = (
    "Give the service account read access in the share permissions and in the "
    "NTFS permissions of the folder."
)


def gateway_from_context(context: CapabilityCheckContext) -> SmbSourceOperations:
    if not isinstance(context.source_operations, SmbSourceOperations):
        raise TypeError(
            "Bug: the runner constructs the registered gateway for migrated sources."
        )
    return context.source_operations


def probe(action: Callable[[], T], failed: str) -> T:
    """Validation errors from the gateway already carry a user-facing message,
    so only unmapped server errors are wrapped."""
    try:
        return action()
    except SmbRequestError as error:
        raise UnexpectedValidationError(f"{failed} {error}") from error


def probe_folders(
    gateway: SmbSourceOperations, config: SmbConnectorConfig
) -> list[tuple[str, list[SmbEntry]]]:
    """The first few folders in scope, breadth first, each with the entries a
    walk reads or follows."""
    folders: list[tuple[str, list[SmbEntry]]] = []
    pending: list[str] = [config.path_prefix]
    excluded: list[str] = [path.casefold() for path in config.excluded_paths or []]
    while pending and len(folders) < FILE_PROBE_MAX_FOLDERS:
        folder: str = pending.pop(0)
        try:
            listing: list[SmbEntry] = gateway.list_folder(path=folder)
        except InsufficientPermissionsError:
            if folder == config.path_prefix:
                raise
            continue
        entries: list[SmbEntry] = [
            entry
            for entry in sorted(listing, key=lambda entry: entry.name)
            if not is_skipped_entry(
                entry, index_offline_files=config.index_offline_files
            )
            and not any(
                join_path(folder, entry.name).casefold() == path
                or join_path(folder, entry.name).casefold().startswith(f"{path}/")
                for path in excluded
            )
        ]
        folders.append((folder, entries))
        pending.extend(
            join_path(folder, entry.name) for entry in entries if entry.is_directory
        )
    return folders


def _smallest_file(
    gateway: SmbSourceOperations, config: SmbConnectorConfig
) -> str | None:
    """The path of the smallest non-empty file that indexing admits, in the
    first probed folder that holds one. Images are left out: the check cannot
    read the image setting."""
    for folder, entries in probe_folders(gateway, config):
        files: list[SmbEntry] = [
            entry
            for entry in entries
            if entry.size > 0
            and is_indexable_file(
                entry, allow_images=False, size_threshold=BLOB_STORAGE_SIZE_THRESHOLD
            )
        ]
        if files:
            return join_path(folder, min(files, key=lambda entry: entry.size).name)
    return None


class _SmbCheck(CapabilityCheck[SmbConnectorConfig]):
    config_class = SmbConnectorConfig

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
            docs_link=DOCS_LINK,
            depends_on=depends_on,
            validates_binding=validates_binding,
            fails_when_unreachable=fails_when_unreachable,
            timeout_text=sign_in_timeout_text("The file server"),
        )


class _ReachableCheck(_SmbCheck):
    def __init__(self) -> None:
        super().__init__(
            check_id=REACHABLE_CHECK_ID,
            display_name="The file server answers on the SMB port",
            remediation=(
                "Check the server name and that a firewall lets Onyx reach TCP "
                "port 445 on it."
            ),
            requires_fields=HOST_FIELDS,
            config_fields=SERVER_FIELDS,
            fails_when_unreachable=True,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        gateway_from_context(context).check_reachable()


def _is_ip_address(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


class _KerberosTicketCheck(_SmbCheck):
    def __init__(self) -> None:
        super().__init__(
            check_id=KERBEROS_TICKET_CHECK_ID,
            display_name="Kerberos issues a ticket",
            remediation=(
                "Check the realm, the username and the password. Set the KDC "
                "host if DNS does not name one, open port 88 from Onyx to it, "
                "and make sure that the clocks agree."
            ),
            requires_fields=HOST_FIELDS,
            config_fields=HOST_FIELDS,
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        gateway = gateway_from_context(context)
        ticket: KerberosTicket | None = probe(
            gateway.get_kerberos_ticket, "The ticket could not be requested."
        )
        if ticket is None:
            raise CheckNotApplicableError("The credential does not use Kerberos.")
        host: str = self.config(context).host
        if not _is_ip_address(host):
            return CheckOutput(
                summary=f"The KDC issued a ticket for {ticket.principal}"
            )
        return CheckOutput(
            summary=f"The KDC issued a ticket for {ticket.principal}",
            advisories=[
                CheckAdvisory(
                    message=(
                        f"The file server '{host}' is an IP address. Kerberos "
                        "needs the server's fully qualified DNS name, so the "
                        "sign-in to the file server fails."
                    )
                )
            ],
        )


class _SignInCheck(_SmbCheck):
    def __init__(self) -> None:
        super().__init__(
            check_id=SIGN_IN_CHECK_ID,
            display_name="Sign in to the file server",
            remediation=(
                "Check the domain, username and password of the service "
                "account, and that the server accepts its sign-in method."
            ),
            requires_fields=HOST_FIELDS,
            config_fields=SESSION_FIELDS,
            depends_on=(REACHABLE_CHECK_ID,),
            validates_binding=True,
            fails_when_unreachable=True,
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        gateway = gateway_from_context(context)
        probe(gateway.connect, "The sign-in could not be checked.")
        credentials = SmbCredentials.model_validate(context.credential_json)
        if credentials.authentication_method is SmbAuthMethod.KERBEROS:
            return CheckOutput(
                summary=f"Signed in as {credentials.kerberos_principal} with Kerberos"
            )
        return CheckOutput(summary=f"Signed in as {credentials.account_name} with NTLM")


class _TransportCheck(_SmbCheck):
    def __init__(self) -> None:
        super().__init__(
            check_id=TRANSPORT_CHECK_ID,
            display_name="The session is signed or encrypted",
            remediation=(
                "Turn on SMB signing on the file server. For encryption, the "
                "server needs SMB 3."
            ),
            requires_fields=HOST_FIELDS,
            config_fields=SESSION_FIELDS,
            depends_on=(SIGN_IN_CHECK_ID,),
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        gateway = gateway_from_context(context)
        session: SmbSessionInfo = probe(
            gateway.connect, "The session could not be checked."
        )
        if session.encrypted:
            return CheckOutput(summary=f"SMB {session.dialect}, encrypted")
        if not session.signing_required:
            raise ConnectorValidationError(
                "The file server did not sign the session, so Onyx cannot "
                "trust what it reads."
            )
        return CheckOutput(
            summary=f"SMB {session.dialect}, signed",
            advisories=[
                CheckAdvisory(
                    message=(
                        "The session is not encrypted, so file content crosses "
                        "the network in the clear. Turn on 'Require encryption' "
                        "if the server supports SMB 3."
                    )
                )
            ],
        )


class _ShareCheck(_SmbCheck):
    def __init__(self) -> None:
        super().__init__(
            check_id=SHARE_CHECK_ID,
            display_name="The share is readable",
            remediation=f"Check the share name. {_READ_REMEDIATION}",
            requires_fields=SHARE_REQUIRED_FIELDS,
            config_fields=SHARE_FIELDS | {"path_prefix"},
            depends_on=(SIGN_IN_CHECK_ID,),
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput | None:
        gateway = gateway_from_context(context)
        try:
            probe(
                lambda: gateway.list_folder(path=""),
                "The share could not be listed.",
            )
        except InsufficientPermissionsError:
            # NTFS access can start below the share root. The path prefix
            # check lists that folder.
            if not self.config(context).path_prefix:
                raise
            return CheckOutput(
                advisories=[
                    CheckAdvisory(
                        message=(
                            "The share root is not readable, so only the path "
                            "prefix is checked."
                        )
                    )
                ]
            )
        return None


class _PathPrefixCheck(_SmbCheck):
    def __init__(self) -> None:
        super().__init__(
            check_id=PATH_PREFIX_CHECK_ID,
            display_name="The path prefix exists",
            remediation="Check the path prefix: a folder in the share.",
            requires_fields=SHARE_REQUIRED_FIELDS,
            config_fields=SHARE_FIELDS | {"path_prefix"},
            depends_on=(SHARE_CHECK_ID,),
        )

    def applies(self, form_state: FormState[SmbConnectorConfig]) -> bool:
        return bool(form_state.config.path_prefix)

    def run(self, context: CapabilityCheckContext) -> None:
        gateway = gateway_from_context(context)
        path_prefix: str = self.config(context).path_prefix
        entry: SmbEntry = probe(
            lambda: gateway.stat(path=path_prefix),
            "The path prefix could not be read.",
        )
        if not entry.is_directory:
            raise ConnectorValidationError(
                f"The path prefix '{path_prefix}' is a file. Enter a folder."
            )
        if entry.is_reparse_point:
            raise ConnectorValidationError(
                f"The path prefix '{path_prefix}' is a junction or a link, "
                "which Onyx does not follow. Enter the folder it points to."
            )
        probe(
            lambda: gateway.list_folder(path=path_prefix),
            "The path prefix could not be listed.",
        )


class _FileReadCheck(_SmbCheck):
    def __init__(self) -> None:
        super().__init__(
            check_id=FILE_READ_CHECK_ID,
            display_name="Files are readable",
            remediation=_READ_REMEDIATION,
            requires_fields=SHARE_REQUIRED_FIELDS,
            config_fields=SCOPE_FIELDS,
            depends_on=(SHARE_CHECK_ID,),
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput | None:
        gateway = gateway_from_context(context)
        config: SmbConnectorConfig = self.config(context)
        path: str | None = probe(
            lambda: _smallest_file(gateway, config), "The files could not be listed."
        )
        if path is None:
            return CheckOutput(
                advisories=[
                    CheckAdvisory(
                        message=(
                            f"No file to read in the first {FILE_PROBE_MAX_FOLDERS} "
                            "folders, so read access was not checked."
                        )
                    )
                ]
            )
        probe(
            lambda: gateway.read_file(path=path, max_bytes=0),
            f"The file {path} could not be read.",
        )
        return None


def build_smb_indexing_checks() -> list[CapabilityCheck]:
    return [
        _ReachableCheck(),
        _KerberosTicketCheck(),
        _SignInCheck(),
        _TransportCheck(),
        _ShareCheck(),
        _PathPrefixCheck(),
        _FileReadCheck(),
    ]
