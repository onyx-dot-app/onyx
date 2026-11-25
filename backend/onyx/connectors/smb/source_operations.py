"""Windows file share gateway: every SMB and LDAP call lives here.

The connector reads one share of one file server with a domain service
account. The session never uses SMB 1, needs SMB 2.1 or later, and requires
signing. Encryption is required unless the connector config turns it off.

``smbclient`` keeps sessions in a connection cache. Each gateway has its own,
so two credentials for one server never share a session.

Permission sync also asks the domain's Active Directory about users and
groups, over LDAP with TLS and the same service account.
"""

import os
import socket
import ssl
import sys
import threading
import weakref
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any, ClassVar, TypeVar

import smbclient
from ldap3 import BASE, NONE, SAFE_SYNC, SIMPLE, SUBTREE, Server, Tls
from ldap3 import Connection as LdapConnection
from ldap3.core.exceptions import (
    LDAPBindError,
    LDAPCertificateError,
    LDAPException,
    LDAPInsufficientAccessRightsResult,
    LDAPInvalidCredentialsResult,
    LDAPSocketOpenError,
    LDAPSocketReceiveError,
    LDAPSocketSendError,
    LDAPStartTLSError,
)
from ldap3.utils.conv import escape_filter_chars
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
    DirectoryGroup,
    DirectoryGroupPage,
    DirectoryInfo,
    DirectoryUser,
    DirectoryUserPage,
    LdapTlsMode,
    SmbCredentials,
    SmbEntry,
    SmbFile,
    SmbSessionInfo,
)
from onyx.connectors.smb.sid import MalformedSidError, rid_of, sid_from_bytes
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

_LDAP_RECEIVE_TIMEOUT_SECONDS = 120
LDAP_PAGE_SIZE = 1000
# A listing still paging past this is a cursor that does not advance.
_MAX_LDAP_PAGES = 10_000
_PAGED_RESULTS_CONTROL = "1.2.840.113556.1.4.319"
# Matches a group and every group nested in it.
_MATCHING_RULE_IN_CHAIN = "1.2.840.113556.1.4.1941"
_MATCHING_RULE_BIT_AND = "1.2.840.113556.1.4.803"
# The groupType bit of a security group. A distribution group grants nothing.
_SECURITY_GROUP_TYPE = 0x80000000
# The userAccountControl bit of a disabled account.
_ACCOUNT_DISABLED = 0x2
_USER_FILTER = "(&(objectCategory=person)(objectClass=user))"
_GROUP_CATEGORY_FILTER = "(objectCategory=group)"
_USER_ATTRIBUTES = ["objectSid", "mail", "userPrincipalName", "userAccountControl"]
_GROUP_ATTRIBUTES = ["objectSid", "cn"]

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
            # An IPv6 address needs brackets in a URL.
            f"https://[{host}]" if ":" in host else f"https://{host}",
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


def _socket(connection: Connection) -> socket.socket | None:
    # smbprotocol has no public handle to its socket.
    transport = connection.transport
    return transport._sock if transport is not None else None  # noqa: SLF001


def _peer_address(connection: Connection) -> str | None:
    """The address the connection's socket reached."""
    sock: socket.socket | None = _socket(connection)
    if sock is None:
        return None
    try:
        return str(sock.getpeername()[0])
    except OSError:
        return None


class _PolicedConnectionCache(dict[str, Connection]):
    """The connection cache smbclient uses for one gateway, with the network
    policy on every server it holds.

    smbclient follows a DFS referral to the server the referral names, and
    signs in there with the same account. It looks a server up here before it
    connects, and stores the connection here before it signs in. So no
    account proof goes to a server that fails the policy: not to a referral
    target, and not to an address that a name resolved to only after the
    check (DNS rebinding).
    """

    def __init__(self) -> None:
        super().__init__()
        self._allowed_hosts: set[str] = set()

    def get(self, key: object, default: Any = None, /) -> Any:
        """``key`` is ``<server>:<port>``."""
        host: str = str(key).rsplit(":", 1)[0]
        if host not in self._allowed_hosts:
            validate_network_host(host, "file server")
            self._allowed_hosts.add(host)
        return super().get(key, default)

    def __setitem__(self, key: str, connection: Connection) -> None:
        peer: str | None = _peer_address(connection)
        try:
            if peer is None:
                raise ConnectorValidationError(
                    f"Onyx cannot tell which address '{key}' connected to."
                )
            validate_network_host(peer, "file server address")
        except ConnectorValidationError:
            connection.disconnect(close=False)
            raise
        super().__setitem__(key, connection)


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


class DirectoryRequestError(SourceApiError):
    """The domain controller answered with an error the gateway does not map."""


def _text(entry: dict[str, Any], attribute: str) -> str | None:
    """The first value of a text attribute. None when the entry has none."""
    values: list[bytes] = entry["raw_attributes"].get(attribute) or []
    return values[0].decode("utf-8", errors="replace") if values else None


def _sid(entry: dict[str, Any]) -> str | None:
    values: list[bytes] = entry["raw_attributes"].get("objectSid") or []
    if not values:
        return None
    try:
        return sid_from_bytes(values[0])
    except MalformedSidError:
        return None


def _directory_user(entry: dict[str, Any]) -> DirectoryUser | None:
    sid: str | None = _sid(entry)
    if sid is None:
        return None
    account_control: str | None = _text(entry, "userAccountControl")
    return DirectoryUser(
        sid=sid,
        mail=_text(entry, "mail"),
        user_principal_name=_text(entry, "userPrincipalName"),
        enabled=not (int(account_control or 0) & _ACCOUNT_DISABLED),
    )


def _directory_group(entry: dict[str, Any]) -> DirectoryGroup | None:
    sid: str | None = _sid(entry)
    if sid is None:
        return None
    return DirectoryGroup(
        sid=sid, distinguished_name=str(entry["dn"]), name=_text(entry, "cn")
    )


class SmbSourceOperations(SourceOperations):
    source = DocumentSource.SMB
    sdk_modules = ("smbclient", "smbprotocol", "spnego", "ldap3")
    config_keys = frozenset(
        {CONFIG_HOST, CONFIG_SHARE, CONFIG_PORT, CONFIG_REQUIRE_ENCRYPTION}
    )

    # Guards the lazy session build: the check runner calls one gateway from
    # several threads. An smbprotocol connection is thread safe.
    _session_lock: ClassVar[threading.RLock] = threading.RLock()
    _connection_cache: dict[str, Connection] | None = None
    _validated_host: str | None = None
    _ldap_connection: LdapConnection | None = None

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
                    cache: dict[str, Connection] = _PolicedConnectionCache()
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
            ) as sock:
                # The name can resolve to another address than the one the
                # policy saw.
                validate_network_host(str(sock.getpeername()[0]), "file server address")
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

    def _directory_host(self, credentials: SmbCredentials) -> str:
        if not credentials.ldap_host:
            raise ConnectorValidationError(
                "The credential names no LDAP host. Permission sync asks a "
                "domain controller about users and groups."
            )
        return credentials.ldap_host

    def _open_ldap(self) -> LdapConnection:
        """A bound connection. The password goes out only after TLS is up
        and the address the socket reached passed the network policy."""
        credentials: SmbCredentials = self._credentials()
        host: str = self._directory_host(credentials)
        validate_network_host(host, "domain controller")
        server = Server(
            host,
            port=credentials.directory_port,
            use_ssl=credentials.ldap_tls is LdapTlsMode.LDAPS,
            tls=Tls(
                validate=ssl.CERT_REQUIRED,
                ca_certs_data=credentials.ldap_ca_cert or None,
            ),
            get_info=NONE,
            connect_timeout=_CONNECTION_TIMEOUT_SECONDS,
        )
        connection = LdapConnection(
            server,
            user=credentials.account_name,
            password=credentials.smb_password,
            authentication=SIMPLE,
            client_strategy=SAFE_SYNC,
            auto_bind=False,
            # A referral names another server. Following it would send the
            # password there.
            auto_referrals=False,
            read_only=True,
            raise_exceptions=True,
            receive_timeout=_LDAP_RECEIVE_TIMEOUT_SECONDS,
        )
        connection.open()
        try:
            ldap_socket: socket.socket | None = connection.socket
            if ldap_socket is None:
                raise UnreachableValidationError(
                    f"Onyx cannot reach the domain controller '{host}'."
                )
            validate_network_host(
                str(ldap_socket.getpeername()[0]), "domain controller address"
            )
            if credentials.ldap_tls is LdapTlsMode.STARTTLS:
                connection.start_tls()
            connection.bind()
        except Exception:
            connection.unbind()
            raise
        return connection

    def _ldap(self) -> LdapConnection:
        if self._ldap_connection is None:
            with self._session_lock:
                if self._ldap_connection is None:
                    self._ldap_connection = self._open_ldap()
        return self._ldap_connection

    def _drop_ldap(self) -> None:
        with self._session_lock:
            connection: LdapConnection | None = self._ldap_connection
            self._ldap_connection = None
        if connection is not None:
            try:
                connection.unbind()
            except LDAPException:
                logger.debug("Closing the LDAP connection failed", exc_info=True)

    def _map_ldap_error(self, error: Exception, target: str) -> Exception:
        host: str = self._credentials().ldap_host
        if isinstance(error, LDAPInvalidCredentialsResult | LDAPBindError):
            return CredentialInvalidError(
                f"The domain controller '{host}' rejected the service account."
            )
        if isinstance(error, LDAPInsufficientAccessRightsResult):
            return InsufficientPermissionsError(
                f"The service account may not read {target} from the directory."
            )
        if isinstance(error, LDAPCertificateError | LDAPStartTLSError | ssl.SSLError):
            return ConnectorValidationError(
                f"Onyx does not trust the TLS certificate of '{host}': {error}. "
                "Add the certificate of the authority that signed it to the "
                "credential, and use the name the certificate holds."
            )
        if isinstance(error, LDAPSocketOpenError | OSError):
            # ldap3 wraps a failed certificate check in a socket error.
            if "certificate" in str(error).lower():
                return ConnectorValidationError(
                    f"Onyx does not trust the TLS certificate of '{host}': "
                    f"{error}. Add the certificate of the authority that "
                    "signed it to the credential, and use the name the "
                    "certificate holds."
                )
            return UnreachableValidationError(
                f"Onyx cannot reach the domain controller '{host}': {error}"
            )
        return DirectoryRequestError(
            f"The domain controller '{host}' failed on {target}: {error}",
            status_code=None,
        )

    def _ldap_search(
        self,
        *,
        base: str,
        search_filter: str,
        attributes: list[str],
        target: str,
        scope: str = SUBTREE,
        cookie: bytes | None = None,
        page_size: int | None = None,
    ) -> tuple[list[dict[str, Any]], bytes | None]:
        """One search, or one page of it. Returns the entries and the cookie
        of the next page. A connection the server closed is made again once."""
        for attempt in range(2):
            try:
                _, result, response, _ = self._ldap().search(
                    base,
                    search_filter,
                    search_scope=scope,
                    attributes=attributes,
                    paged_size=page_size,
                    paged_cookie=cookie,
                )
            except (LDAPSocketReceiveError, LDAPSocketSendError) as e:
                self._drop_ldap()
                if attempt:
                    raise self._map_ldap_error(e, target) from e
                continue
            except (ConnectorValidationError, SourceApiError):
                raise
            except (LDAPException, OSError) as e:
                self._drop_ldap()
                raise self._map_ldap_error(e, target) from e
            entries: list[dict[str, Any]] = [
                entry
                for entry in response or []
                if entry.get("type") == "searchResEntry"
            ]
            next_cookie: bytes | None = (
                ((result.get("controls") or {}).get(_PAGED_RESULTS_CONTROL) or {})
                .get("value", {})
                .get("cookie")
            )
            return entries, next_cookie or None
        raise RuntimeError("Bug: the retry loop always returns or raises.")

    @source_operation(
        capabilities=(CredentialCapability.EXTERNAL_GROUP_SYNC,),
        consumes=OperationConsumes.CREDENTIAL,
    )
    def get_directory_info(self) -> DirectoryInfo:
        """Binds to the domain controller and reads the domain's name and SID."""
        target: str = "the domain"
        roots, _ = self._ldap_search(
            base="",
            search_filter="(objectClass=*)",
            attributes=["defaultNamingContext"],
            scope=BASE,
            target=target,
        )
        base_dn: str | None = _text(roots[0], "defaultNamingContext") if roots else None
        if not base_dn:
            raise DirectoryRequestError(
                "The LDAP server names no domain. Is it an Active Directory "
                "domain controller?",
                status_code=None,
            )
        domains, _ = self._ldap_search(
            base=base_dn,
            search_filter="(objectClass=*)",
            attributes=["objectSid"],
            scope=BASE,
            target=target,
        )
        domain_sid: str | None = _sid(domains[0]) if domains else None
        if domain_sid is None:
            raise InsufficientPermissionsError(
                f"The service account may not read the domain object '{base_dn}'."
            )
        return DirectoryInfo(base_dn=base_dn, domain_sid=domain_sid)

    @source_operation(
        capabilities=(CredentialCapability.EXTERNAL_GROUP_SYNC,),
        consumes=OperationConsumes.CREDENTIAL,
    )
    def list_directory_users(
        self,
        *,
        base_dn: str,
        cookie: bytes | None = None,
        page_size: int = LDAP_PAGE_SIZE,
    ) -> DirectoryUserPage:
        """One page of the domain's user accounts. Computers are left out."""
        entries, next_cookie = self._ldap_search(
            base=base_dn,
            search_filter=_USER_FILTER,
            attributes=_USER_ATTRIBUTES,
            cookie=cookie,
            page_size=page_size,
            target="the domain's users",
        )
        return DirectoryUserPage(
            users=[
                user
                for entry in entries
                if (user := _directory_user(entry)) is not None
            ],
            cookie=next_cookie,
        )

    @source_operation(
        capabilities=(CredentialCapability.EXTERNAL_GROUP_SYNC,),
        consumes=OperationConsumes.CREDENTIAL,
    )
    def list_directory_groups(
        self,
        *,
        base_dn: str,
        cookie: bytes | None = None,
        page_size: int = LDAP_PAGE_SIZE,
    ) -> DirectoryGroupPage:
        """One page of the domain's security groups."""
        entries, next_cookie = self._ldap_search(
            base=base_dn,
            search_filter=(
                f"(&{_GROUP_CATEGORY_FILTER}"
                f"(groupType:{_MATCHING_RULE_BIT_AND}:={_SECURITY_GROUP_TYPE}))"
            ),
            attributes=_GROUP_ATTRIBUTES,
            cookie=cookie,
            page_size=page_size,
            target="the domain's groups",
        )
        return DirectoryGroupPage(
            groups=[
                group
                for entry in entries
                if (group := _directory_group(entry)) is not None
            ],
            cookie=next_cookie,
        )

    @source_operation(
        capabilities=(CredentialCapability.EXTERNAL_GROUP_SYNC,),
        consumes=OperationConsumes.CREDENTIAL,
    )
    def find_directory_group(self, *, base_dn: str, sid: str) -> DirectoryGroup | None:
        """The domain group with this SID. None for a SID the domain does not
        know as a group, e.g. a local group of the file server."""
        entries, _ = self._ldap_search(
            base=base_dn,
            search_filter=(
                f"(&{_GROUP_CATEGORY_FILTER}(objectSid={escape_filter_chars(sid)}))"
            ),
            attributes=_GROUP_ATTRIBUTES,
            target=f"the group {sid}",
        )
        return _directory_group(entries[0]) if entries else None

    @source_operation(
        capabilities=(CredentialCapability.EXTERNAL_GROUP_SYNC,),
        consumes=OperationConsumes.CREDENTIAL,
    )
    def list_group_member_sids(
        self, *, base_dn: str, group: DirectoryGroup
    ) -> list[str]:
        """The SIDs of the users in a group, members of nested groups
        included. A user's primary group is not in ``memberOf``, so it is
        matched by its id."""
        member_filter: str = (
            f"(&{_USER_FILTER}(|"
            f"(memberOf:{_MATCHING_RULE_IN_CHAIN}:="
            f"{escape_filter_chars(group.distinguished_name)})"
            f"(primaryGroupID={rid_of(group.sid)})))"
        )
        sids: list[str] = []
        cookie: bytes | None = None
        for _ in range(_MAX_LDAP_PAGES):
            entries, cookie = self._ldap_search(
                base=base_dn,
                search_filter=member_filter,
                attributes=["objectSid"],
                cookie=cookie,
                page_size=LDAP_PAGE_SIZE,
                target=f"the members of the group {group.sid}",
            )
            sids.extend(sid for entry in entries if (sid := _sid(entry)) is not None)
            if cookie is None:
                return sids
        raise RuntimeError(f"The members of {group.sid} passed {_MAX_LDAP_PAGES} pages")


def _enable_keepalive(connection: Connection) -> None:
    """Makes TCP close a connection whose peer stopped answering."""
    sock: socket.socket | None = _socket(connection)
    if sock is None:
        return
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        # The timing options are Linux names. Without them the OS defaults apply.
        if sys.platform != "linux":
            return
        sock.setsockopt(
            socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, _KEEPALIVE_IDLE_SECONDS
        )
        sock.setsockopt(
            socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, _KEEPALIVE_INTERVAL_SECONDS
        )
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, _KEEPALIVE_PROBES)
    except OSError:
        logger.debug("TCP keepalive is not available", exc_info=True)
