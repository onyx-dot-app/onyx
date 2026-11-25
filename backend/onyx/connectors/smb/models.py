from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from onyx.connectors.models import ConnectorCheckpoint

# https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-fscc/ca28ec38-f155-4768-81d6-4bfeb8586fc9
FILE_ATTRIBUTE_DIRECTORY = 0x10
FILE_ATTRIBUTE_REPARSE_POINT = 0x400
FILE_ATTRIBUTE_OFFLINE = 0x1000
FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x40000
FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x400000
# A read of a file with one of these bits recalls it from tiered storage.
OFFLINE_ATTRIBUTES = (
    FILE_ATTRIBUTE_OFFLINE
    | FILE_ATTRIBUTE_RECALL_ON_OPEN
    | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS
)


class SmbAuthMethod(str, Enum):
    NTLM = "ntlm"
    # For a network that turns NTLM off. Needs the server's DNS name.
    KERBEROS = "kerberos"


class LdapTlsMode(str, Enum):
    """How the directory connection is encrypted. There is no plain mode: the
    bind sends the service account's password."""

    LDAPS = "ldaps"
    STARTTLS = "starttls"


LDAP_DEFAULT_PORTS: dict[LdapTlsMode, int] = {
    LdapTlsMode.LDAPS: 636,
    LdapTlsMode.STARTTLS: 389,
}
_MAX_PORT = 65535


class SmbCredentials(BaseModel):
    """A domain service account, and the domain controller that permission
    sync asks about users and groups."""

    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)

    authentication_method: SmbAuthMethod = SmbAuthMethod.NTLM
    # The NetBIOS or DNS name of the domain. Empty for a local account of the
    # file server.
    smb_domain: str = ""
    smb_username: str
    smb_password: str
    # Empty when permission sync is not used.
    ldap_host: str = ""
    # None uses the TLS mode's standard port.
    ldap_port: int | None = Field(default=None, ge=1, le=_MAX_PORT)
    ldap_tls: LdapTlsMode = LdapTlsMode.LDAPS
    # PEM certificates of the authority that signed the domain controller's
    # certificate. Empty uses the system's trusted authorities.
    ldap_ca_cert: str = ""
    # The Active Directory domain's DNS name in upper case. For Kerberos only.
    kerberos_realm: str = ""
    # A domain controller that issues tickets. Empty finds one through DNS.
    kerberos_kdc: str = ""

    @field_validator("kerberos_realm", mode="before")
    @classmethod
    def _upper_realm(cls, value: Any) -> Any:
        return value.strip().upper() if isinstance(value, str) else (value or "")

    @field_validator("kerberos_kdc", mode="before")
    @classmethod
    def _strip_kdc(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else (value or "")

    @model_validator(mode="after")
    def _kerberos_names_a_realm(self) -> "SmbCredentials":
        if (
            self.authentication_method is SmbAuthMethod.KERBEROS
            and not self.kerberos_realm
        ):
            raise ValueError("Kerberos needs the realm of the domain.")
        return self

    @property
    def kerberos_principal(self) -> str:
        """``user@REALM``. A domain prefix on the username is dropped: the
        realm names the domain."""
        if "@" in self.smb_username:
            return self.smb_username
        return f"{self.smb_username.rsplit('\\', 1)[-1]}@{self.kerberos_realm}"

    @field_validator("ldap_tls", mode="before")
    @classmethod
    def _missing_means_ldaps(cls, value: Any) -> Any:
        return value or LdapTlsMode.LDAPS

    @field_validator("ldap_port", mode="before")
    @classmethod
    def _blank_port_means_default(cls, value: Any) -> Any:
        return None if value in ("", None) else value

    @field_validator("ldap_host", "ldap_ca_cert", mode="before")
    @classmethod
    def _strip_directory_fields(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else (value or "")

    @property
    def directory_port(self) -> int:
        return self.ldap_port or LDAP_DEFAULT_PORTS[self.ldap_tls]

    @field_validator("authentication_method", mode="before")
    @classmethod
    def _missing_means_ntlm(cls, value: Any) -> Any:
        return value or SmbAuthMethod.NTLM

    @field_validator("smb_domain", "smb_username", mode="before")
    @classmethod
    def _strip(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @field_validator("smb_username", "smb_password")
    @classmethod
    def _not_empty(cls, value: str) -> str:
        if not value:
            raise ValueError("The username and the password must be set.")
        return value

    @property
    def account_name(self) -> str:
        """The account as SMB sign-in takes it. A username that already names
        its domain (``DOMAIN\\user`` or ``user@domain``) is used as entered."""
        if not self.smb_domain or "\\" in self.smb_username or "@" in self.smb_username:
            return self.smb_username
        return f"{self.smb_domain}\\{self.smb_username}"


class SmbEntry(BaseModel):
    """One entry of a folder listing, or the answer of a stat."""

    # The name as the server returns it. Windows keeps the case of a name.
    name: str
    # The raw FILE_ATTRIBUTE_* bits.
    attributes: int
    creation_time: datetime
    last_write_time: datetime
    # Changes with the content, a rename, a move and an ACL change.
    change_time: datetime
    size: int

    @property
    def is_directory(self) -> bool:
        return bool(self.attributes & FILE_ATTRIBUTE_DIRECTORY)

    @property
    def is_reparse_point(self) -> bool:
        """A junction, a symlink or a DFS link."""
        return bool(self.attributes & FILE_ATTRIBUTE_REPARSE_POINT)

    @property
    def is_offline(self) -> bool:
        return bool(self.attributes & OFFLINE_ATTRIBUTES)

    @property
    def changed_at(self) -> datetime:
        """A file copied onto the share keeps its old last write time, so the
        newest of the three timestamps says when the share last saw a change."""
        return max(self.creation_time, self.last_write_time, self.change_time)


class SmbFile(BaseModel):
    size: int
    # None when the file is larger than the caller's limit.
    content: bytes | None


class KerberosTicket(BaseModel):
    """A ticket-granting ticket that the KDC issued for the service account."""

    principal: str


class SmbSessionInfo(BaseModel):
    """What the server and Onyx negotiated."""

    # E.g. "3.1.1".
    dialect: str
    signing_required: bool
    encrypted: bool


class EmailAttribute(str, Enum):
    """The Active Directory attribute that holds a user's Onyx login email."""

    # ``mail``, and ``userPrincipalName`` for a user with no ``mail``.
    MAIL = "mail"
    USER_PRINCIPAL_NAME = "userPrincipalName"


class DirectoryInfo(BaseModel):
    """The domain the directory connection is bound to."""

    # E.g. "DC=corp,DC=example,DC=com".
    base_dn: str
    domain_sid: str


class DirectoryUser(BaseModel):
    sid: str
    mail: str | None = None
    user_principal_name: str | None = None
    # False for a disabled account, which cannot sign in.
    enabled: bool = True


class DirectoryGroup(BaseModel):
    sid: str
    distinguished_name: str
    name: str | None = None


class DirectoryUserPage(BaseModel):
    users: list[DirectoryUser]
    # None after the last page.
    cookie: bytes | None


class DirectoryGroupPage(BaseModel):
    groups: list[DirectoryGroup]
    cookie: bytes | None


class SmbPendingFolder(BaseModel):
    # Relative to the share root, with "/" between names. Empty for the root.
    path: str
    last_write_time: datetime | None = None
    # True when the folder or one above it was renamed or moved in the poll
    # window. Its files have new document ids, so all of them are indexed.
    index_all: bool = False


class SmbCheckpoint(ConnectorCheckpoint):
    started: bool = False
    # Folders still to walk. The last one is walked next.
    pending: list[SmbPendingFolder] = []
    current: SmbPendingFolder | None = None
    # The last name done in ``current``, in sorted order. None before the first.
    last_name: str | None = None
