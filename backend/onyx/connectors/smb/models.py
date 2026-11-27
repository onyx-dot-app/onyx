from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

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


class SmbCredentials(BaseModel):
    """A domain service account."""

    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)

    authentication_method: SmbAuthMethod = SmbAuthMethod.NTLM
    # The NetBIOS or DNS name of the domain. Empty for a local account of the
    # file server.
    smb_domain: str = ""
    smb_username: str
    smb_password: str

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


class SmbSessionInfo(BaseModel):
    """What the server and Onyx negotiated."""

    # E.g. "3.1.1".
    dialect: str
    signing_required: bool
    encrypted: bool


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
