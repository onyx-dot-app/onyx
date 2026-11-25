"""Windows file share gateway: every SMB call lives here.

The connector reads one share of one file server with a domain service
account. The session never uses SMB 1, needs SMB 2.1 or later, and requires
signing. Encryption is required unless the connector config turns it off.

``smbclient`` keeps sessions in a connection cache. Each gateway has its own,
so two credentials for one server never share a session.
"""

import os
import socket
import threading
import weakref
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any, ClassVar, TypeVar

import smbclient
from pydantic import ValidationError
from smbprotocol.connection import Connection
from smbprotocol.exceptions import (
    SMBAuthenticationError,
    SMBConnectionClosed,
    SMBException,
    SMBOSError,
    SMBResponseException,
)
from smbprotocol.session import Session

from onyx.configs.constants import DocumentSource
from onyx.connectors.capabilities import CredentialCapability
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialInvalidError,
    InsufficientPermissionsError,
    SourceApiError,
    UnreachableValidationError,
)
from onyx.connectors.smb.config import (
    DEFAULT_SMB_PORT,
    SmbConnectorConfig,
    SmbCredentialBinding,
)
from onyx.connectors.smb.models import (
    SmbCredentials,
    SmbEntry,
    SmbFile,
    SmbSessionInfo,
)
from onyx.connectors.source_operations import (
    OperationConsumes,
    SourceOperations,
    source_operation,
)
from onyx.server.security.models import connector_ssrf_enforced
from onyx.server.security.store import get_security_settings
from onyx.utils.logger import setup_logger
from onyx.utils.url import SSRFException, validate_outbound_http_url
from shared_configs.configs import MULTI_TENANT

logger = setup_logger()

CONFIG_HOST = "host"
CONFIG_SHARE = "share"
CONFIG_PORT = "port"
CONFIG_REQUIRE_ENCRYPTION = "require_encryption"

_CONNECTION_TIMEOUT_SECONDS = 20
# A peer that stops answering closes the connection after about two minutes.
# smbprotocol waits for a response with no time limit of its own.
_KEEPALIVE_IDLE_SECONDS = 60
_KEEPALIVE_INTERVAL_SECONDS = 15
_KEEPALIVE_PROBES = 4
# Let other clients read, write and delete a file while Onyx reads it.
_SHARE_ALL = "rwd"
_SMB_2_1 = 0x210
_DIALECT_NAMES: dict[int, str] = {
    0x202: "2.0.2",
    _SMB_2_1: "2.1",
    0x300: "3.0",
    0x302: "3.0.2",
    0x311: "3.1.1",
}

# NTSTATUS values:
# https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-erref/596a1078-e883-4972-9bbc-49e60bebca55
STATUS_ACCESS_DENIED = 0xC0000022
_ACCESS_DENIED_STATUSES = frozenset(
    {
        STATUS_ACCESS_DENIED,
        0xC0000061,  # STATUS_PRIVILEGE_NOT_HELD
        0xC00000CA,  # STATUS_NETWORK_ACCESS_DENIED
    }
)
_NOT_FOUND_STATUSES = frozenset(
    {
        0xC000000F,  # STATUS_NO_SUCH_FILE
        0xC0000033,  # STATUS_OBJECT_NAME_INVALID
        0xC0000034,  # STATUS_OBJECT_NAME_NOT_FOUND
        0xC000003A,  # STATUS_OBJECT_PATH_NOT_FOUND
        0xC0000056,  # STATUS_DELETE_PENDING
        0xC00000BA,  # STATUS_FILE_IS_A_DIRECTORY
        0xC0000103,  # STATUS_NOT_A_DIRECTORY
        0xC0000225,  # STATUS_NOT_FOUND
    }
)
_LOGON_STATUSES = frozenset(
    {
        0xC000006A,  # STATUS_WRONG_PASSWORD
        0xC000006D,  # STATUS_LOGON_FAILURE
        0xC000006E,  # STATUS_ACCOUNT_RESTRICTION
        0xC000006F,  # STATUS_INVALID_LOGON_HOURS
        0xC0000070,  # STATUS_INVALID_WORKSTATION
        0xC0000071,  # STATUS_PASSWORD_EXPIRED
        0xC0000072,  # STATUS_ACCOUNT_DISABLED
        0xC0000224,  # STATUS_PASSWORD_MUST_CHANGE
        0xC0000234,  # STATUS_ACCOUNT_LOCKED_OUT
    }
)
_NO_SHARE_STATUSES = frozenset(
    {
        0xC00000C9,  # STATUS_NETWORK_NAME_DELETED
        0xC00000CC,  # STATUS_BAD_NETWORK_NAME
    }
)

T = TypeVar("T")


class SmbRequestError(SourceApiError):
    """The file server answered with an error the gateway does not map."""


class SmbNotFoundError(ConnectorValidationError):
    """The file or folder does not exist, e.g. it was deleted or renamed after
    the listing."""


class SmbAccessDeniedError(InsufficientPermissionsError):
    """The service account may not open the file or folder."""


def validate_network_host(host: str, role: str) -> None:
    """Applies the shared connector network policy to a host an admin names.
    A file server is on a private network in the normal case, which a
    multi-tenant deployment must never reach. Elsewhere the SSRF protection
    level decides: private hosts are reachable only when an admin relaxed it,
    and cloud metadata stays blocked either way."""
    if MULTI_TENANT:
        raise ConnectorValidationError(
            "Windows file shares are available on self-hosted Onyx only."
        )
    enforced: bool = connector_ssrf_enforced(
        get_security_settings().ssrf_protection_level
    )
    try:
        validate_outbound_http_url(
            f"https://{host}",
            allow_private_network=not enforced,
            block_link_local_only=not enforced,
        )
    except (SSRFException, ValueError) as e:
        hint: str = (
            " To reach a host on a private network, an operator must lower the "
            "SSRF protection level in the security settings."
            if enforced
            else ""
        )
        raise ConnectorValidationError(
            f"Onyx may not connect to the {role} '{host}': {e}.{hint}"
        ) from e


def _close_connections(connection_cache: dict[str, Connection]) -> None:
    try:
        smbclient.reset_connection_cache(
            fail_on_error=False, connection_cache=connection_cache
        )
    except Exception:
        logger.debug("Closing SMB connections failed", exc_info=True)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _from_timestamp(seconds: float) -> datetime:
    return datetime.fromtimestamp(seconds, tz=timezone.utc)


def _dialect(connection: Connection) -> int:
    dialect: int | None = connection.dialect
    if dialect is None:
        raise RuntimeError("Bug: a connected session has a negotiated dialect.")
    return dialect


def _dialect_name(dialect: int) -> str:
    return _DIALECT_NAMES.get(dialect, hex(dialect))


def _status(error: Exception) -> int | None:
    if isinstance(error, SMBOSError):
        return error.ntstatus
    if isinstance(error, SMBResponseException):
        return error.status
    return None


class SmbSourceOperations(SourceOperations):
    source = DocumentSource.SMB
    sdk_modules = ("smbclient", "smbprotocol", "spnego")
    config_keys = frozenset(
        {CONFIG_HOST, CONFIG_SHARE, CONFIG_PORT, CONFIG_REQUIRE_ENCRYPTION}
    )

    # Guards the lazy session build: the check runner calls one gateway from
    # several threads. An smbprotocol connection is thread safe.
    _session_lock: ClassVar[threading.RLock] = threading.RLock()
    _connection_cache: dict[str, Connection] | None = None
    _validated_host: str | None = None

    def _config(self) -> SmbConnectorConfig:
        try:
            return SmbConnectorConfig.model_validate(
                self.connector_specific_config or {}
            )
        except ValidationError as e:
            raise ConnectorValidationError("Set a valid file server and share.") from e

    def _host(self) -> str:
        """The file server alone, which the reachability and sign-in checks
        need before a share is chosen."""
        try:
            return SmbCredentialBinding.model_validate(
                self.connector_specific_config or {}
            ).host
        except ValidationError as e:
            raise ConnectorValidationError("Set a valid file server.") from e

    def _port(self) -> int:
        value: Any = (self.connector_specific_config or {}).get(CONFIG_PORT)
        return int(value) if value else DEFAULT_SMB_PORT

    def _require_encryption(self) -> bool:
        value: Any = (self.connector_specific_config or {}).get(
            CONFIG_REQUIRE_ENCRYPTION
        )
        return True if value is None else bool(value)

    def _credentials(self) -> SmbCredentials:
        try:
            return SmbCredentials.model_validate(
                self.credentials_provider.get_credentials()
            )
        except ValidationError as e:
            raise CredentialInvalidError(
                "The credential is not a Windows file share credential."
            ) from e

    def _checked_host(self) -> str:
        host: str = self._host()
        if self._validated_host != host:
            validate_network_host(host, "file server")
            self._validated_host = host
        return host

    def _cache(self) -> dict[str, Connection]:
        if self._connection_cache is None:
            with self._session_lock:
                if self._connection_cache is None:
                    cache: dict[str, Connection] = {}
                    # Each connection owns a socket and a reader thread.
                    weakref.finalize(self, _close_connections, cache)
                    self._connection_cache = cache
        return self._connection_cache

    def _session_kwargs(self) -> dict[str, Any]:
        """The connection arguments every smbclient call takes."""
        credentials: SmbCredentials = self._credentials()
        return {
            "username": credentials.account_name,
            "password": credentials.smb_password,
            "port": self._port(),
            # None lets the server decide.
            "encrypt": True if self._require_encryption() else None,
            "connection_timeout": _CONNECTION_TIMEOUT_SECONDS,
            "connection_cache": self._cache(),
            "auth_protocol": credentials.authentication_method.value,
            "require_signing": True,
        }

    def _session(self) -> Session:
        """The signed-in session, made once. smbclient reuses it for every
        call with the same arguments."""
        host: str = self._checked_host()
        with self._session_lock:
            session: Session = smbclient.register_session(
                host, **self._session_kwargs()
            )
            connection: Connection = session.connection
            dialect: int = _dialect(connection)
            if dialect < _SMB_2_1:
                _close_connections(self._cache())
                raise ConnectorValidationError(
                    f"The file server '{host}' offers only SMB "
                    f"{_dialect_name(dialect)}. Onyx needs SMB 2.1 or later."
                )
            _enable_keepalive(connection)
            return session

    def _unc(self, path: str) -> str:
        """The UNC path of a path inside the share. Empty for the share root."""
        config: SmbConnectorConfig = self._config()
        root: str = f"\\\\{config.host}\\{config.share}"
        return f"{root}\\{path.replace('/', '\\')}" if path else root

    def _map_error(self, error: Exception, target: str) -> Exception:
        host: str = self._host()
        status: int | None = _status(error)
        if isinstance(error, SMBAuthenticationError) or status in _LOGON_STATUSES:
            return CredentialInvalidError(
                f"The file server '{host}' rejected the service account: {error}"
            )
        if status in _ACCESS_DENIED_STATUSES:
            return SmbAccessDeniedError(
                f"The service account may not read {target}. Give it read access."
            )
        if status in _NO_SHARE_STATUSES:
            return ConnectorValidationError(
                f"The share '{self._config().share}' does not exist on '{host}'."
            )
        if status in _NOT_FOUND_STATUSES:
            return SmbNotFoundError(f"{target} does not exist.")
        if status is not None:
            return SmbRequestError(
                f"The file server '{host}' failed on {target}: {error}",
                status_code=None,
            )
        if isinstance(error, SMBConnectionClosed | OSError | ValueError):
            return UnreachableValidationError(
                f"Onyx cannot reach the file server '{host}' on port "
                f"{self._port()}: {error}"
            )
        if isinstance(error, SMBException) and "encrypt" in str(error).lower():
            return ConnectorValidationError(
                f"The file server '{host}' does not support SMB 3 encryption. "
                "Turn off 'Require encryption' only if the server cannot be "
                "upgraded."
            )
        return SmbRequestError(
            f"The file server '{host}' failed on {target}: {error}", status_code=None
        )

    def _call(self, action: Callable[[], T], target: str) -> T:
        """Runs one SMB request and maps its failure. ``target`` names what
        was requested, for the message. A connection that the server closed
        is made again once."""
        for attempt in range(2):
            try:
                self._session()
                return action()
            except SMBConnectionClosed as e:
                _close_connections(self._cache())
                if attempt:
                    raise self._map_error(e, target) from e
            except (ConnectorValidationError, SourceApiError):
                raise
            # smbprotocol raises ValueError for a failed TCP connection.
            except (SMBException, OSError, ValueError) as e:
                raise self._map_error(e, target) from e
        raise RuntimeError("Bug: the retry loop always returns or raises.")

    @source_operation(
        capabilities=(CredentialCapability.INDEXING,),
        consumes=OperationConsumes.CONFIG,
    )
    def check_reachable(self) -> None:
        """Opens and closes a TCP connection to the SMB port."""
        host: str = self._checked_host()
        port: int = self._port()
        try:
            with socket.create_connection(
                (host, port), timeout=_CONNECTION_TIMEOUT_SECONDS
            ):
                return
        except OSError as e:
            raise UnreachableValidationError(
                f"Onyx cannot reach the file server '{host}' on port {port}: {e}"
            ) from e

    @source_operation(
        capabilities=(CredentialCapability.INDEXING,),
        consumes=OperationConsumes.BOTH,
    )
    def connect(self) -> SmbSessionInfo:
        """Signs in to the file server and reports what was negotiated."""

        def info() -> SmbSessionInfo:
            session: Session = self._session()
            connection: Connection = session.connection
            encrypted: bool = bool(session.encrypt_data)
            return SmbSessionInfo(
                dialect=_dialect_name(_dialect(connection)),
                # An encrypted message is not signed again: encryption
                # authenticates it.
                signing_required=bool(session.signing_required) or encrypted,
                encrypted=encrypted,
            )

        return self._call(info, "the sign-in")

    @source_operation(
        capabilities=(CredentialCapability.INDEXING,),
        consumes=OperationConsumes.BOTH,
    )
    def list_folder(self, *, path: str) -> list[SmbEntry]:
        """Every entry of one folder, in the server's order. The listing
        carries each entry's attributes and timestamps, so a walk needs no
        request per file."""
        unc: str = self._unc(path)

        def read() -> list[SmbEntry]:
            return [
                SmbEntry(
                    name=entry.name,
                    attributes=entry.smb_info.file_attributes,
                    creation_time=_aware(entry.smb_info.creation_time),
                    last_write_time=_aware(entry.smb_info.last_write_time),
                    change_time=_aware(entry.smb_info.change_time),
                    size=entry.smb_info.end_of_file,
                )
                for entry in smbclient.scandir(unc, **self._session_kwargs())
            ]

        try:
            return self._call(read, f"the folder '{unc}'")
        except SmbNotFoundError as e:
            if path:
                raise
            # smbclient looks for a DFS referral before it gives up on a
            # share, and then reports the share as a missing path.
            raise ConnectorValidationError(
                f"The share '{self._config().share}' does not exist on "
                f"'{self._host()}'."
            ) from e

    @source_operation(
        capabilities=(CredentialCapability.INDEXING,),
        consumes=OperationConsumes.BOTH,
    )
    def stat(self, *, path: str) -> SmbEntry:
        """One file or folder. A reparse point is not followed."""
        unc: str = self._unc(path)

        def read() -> SmbEntry:
            result = smbclient.stat(
                unc, follow_symlinks=False, **self._session_kwargs()
            )
            return SmbEntry(
                name=path.rsplit("/", 1)[-1],
                attributes=result.st_file_attributes,
                # smbclient names the creation time st_ctime.
                creation_time=_from_timestamp(result.st_ctime),
                last_write_time=_from_timestamp(result.st_mtime),
                change_time=_from_timestamp(result.st_chgtime),
                size=result.st_size,
            )

        return self._call(read, f"'{unc}'")

    @source_operation(
        capabilities=(CredentialCapability.INDEXING,),
        consumes=OperationConsumes.BOTH,
    )
    def read_file(self, *, path: str, max_bytes: int) -> SmbFile:
        """The file's content, or None for it when the file is larger than
        ``max_bytes``."""
        unc: str = self._unc(path)

        def download() -> SmbFile:
            with smbclient.open_file(
                unc, mode="rb", share_access=_SHARE_ALL, **self._session_kwargs()
            ) as file:
                size: int = file.seek(0, os.SEEK_END)
                if size > max_bytes:
                    return SmbFile(size=size, content=None)
                file.seek(0)
                # One byte more shows a file that grew after the size was read.
                content: bytes = file.read(max_bytes + 1)
                if len(content) > max_bytes:
                    return SmbFile(size=len(content), content=None)
                return SmbFile(size=len(content), content=content)

        return self._call(download, f"the file '{unc}'")


def _enable_keepalive(connection: Connection) -> None:
    """Makes TCP close a connection whose peer stopped answering."""
    # smbprotocol has no public handle to its socket.
    transport = connection.transport
    sock: socket.socket | None = (
        transport._sock if transport is not None else None  # noqa: SLF001
    )
    if sock is None:
        return
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        sock.setsockopt(
            socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, _KEEPALIVE_IDLE_SECONDS
        )
        sock.setsockopt(
            socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, _KEEPALIVE_INTERVAL_SECONDS
        )
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, _KEEPALIVE_PROBES)
    except (OSError, AttributeError):
        # The options are Linux names. Without them the connection still works.
        logger.debug("TCP keepalive is not available", exc_info=True)
