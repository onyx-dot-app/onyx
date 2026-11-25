import re
from typing import Annotated, Any

from pydantic import Field, field_validator

from onyx.connectors.connector_config import (
    ConnectorConfig,
    CredentialBinding,
    field_format_error,
)
from onyx.connectors.field_policy import (
    FieldClass,
    FieldPolicy,
    ScopeExclude,
    ScopeOpaque,
    ScopeToggle,
)
from onyx.connectors.smb.models import EmailAttribute

DEFAULT_SMB_PORT = 445
# A DNS name or an IPv4 address.
_HOST_PATTERN = re.compile(r"[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?")
# https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-dtyp/dc9978d7-6299-4c5a-a22d-a039cdc716ea
_SHARE_PATTERN = re.compile(r"[^\\/:*?\"<>|\x00-\x1f]{1,80}")
# The pipe share holds no files.
_IPC_SHARE = "ipc$"
_MAX_PORT = 65535


def normalize_path(value: str) -> str:
    """A path inside the share with "/" between names and none at the ends."""
    return "/".join(
        part for part in value.strip().replace("\\", "/").split("/") if part
    )


def _has_relative_part(path: str) -> bool:
    return any(part in (".", "..") for part in path.split("/"))


class SmbCredentialBinding(CredentialBinding):
    # The service account's password proof goes to this host.
    host: Annotated[str, FieldPolicy(FieldClass.IDENTITY)]

    @field_validator("host", mode="before")
    @classmethod
    def _strip_host(cls, value: Any) -> Any:
        return value.strip().strip("\\/") if isinstance(value, str) else value

    @field_validator("host")
    @classmethod
    def _valid_host(cls, value: str) -> str:
        if not _HOST_PATTERN.fullmatch(value):
            raise field_format_error(
                "Enter the file server's DNS name or IPv4 address, without the share."
            )
        return value


class SmbConnectorConfig(SmbCredentialBinding, ConnectorConfig):
    # Document ids contain the share name.
    share: Annotated[str, FieldPolicy(FieldClass.IDENTITY)]
    # A path prefix, not a list: a longer prefix narrows and a shorter one widens.
    path_prefix: Annotated[str, FieldPolicy(FieldClass.SCOPE, scope=ScopeOpaque())] = ""
    # Folders to skip, as paths from the share root. A path can hold a comma.
    excluded_paths: Annotated[
        list[str] | None,
        FieldPolicy(FieldClass.SCOPE, scope=ScopeExclude(split_on_commas=False)),
    ] = None
    # False admits a server without SMB 3 encryption. Signing stays required.
    require_encryption: Annotated[bool, FieldPolicy(FieldClass.COSMETIC)] = True
    # True also reads files in tiered storage, which recalls each one.
    index_offline_files: Annotated[
        bool, FieldPolicy(FieldClass.SCOPE, scope=ScopeToggle(widens_when=True))
    ] = False
    port: Annotated[int, FieldPolicy(FieldClass.COSMETIC)] = Field(
        default=DEFAULT_SMB_PORT, ge=1, le=_MAX_PORT
    )
    # Permission sync matches this attribute to the Onyx login email.
    email_attribute: Annotated[EmailAttribute, FieldPolicy(FieldClass.COSMETIC)] = (
        EmailAttribute.MAIL
    )

    @field_validator("share", mode="before")
    @classmethod
    def _strip_share(cls, value: Any) -> Any:
        return value.strip().strip("\\/") if isinstance(value, str) else value

    @field_validator("share")
    @classmethod
    def _valid_share(cls, value: str) -> str:
        if not _SHARE_PATTERN.fullmatch(value) or value.lower() == _IPC_SHARE:
            raise field_format_error(
                "Enter the share name alone, e.g. Plans for \\\\server\\Plans."
            )
        return value

    @field_validator("path_prefix", mode="before")
    @classmethod
    def _normalize_path_prefix(cls, value: Any) -> Any:
        return normalize_path(value) if isinstance(value, str) else value

    @field_validator("path_prefix")
    @classmethod
    def _valid_path_prefix(cls, value: str) -> str:
        if _has_relative_part(value):
            raise field_format_error("Enter a folder path without . or .. parts.")
        return value

    @field_validator("excluded_paths", mode="before")
    @classmethod
    def _normalize_excluded_paths(cls, value: Any) -> Any:
        """Sorted and without duplicates, so the same set always saves as the
        same value."""
        if not isinstance(value, list):
            return value
        if not all(isinstance(path, str) for path in value):
            return value
        paths: set[str] = {normalize_path(path) for path in value}
        return sorted(path for path in paths if path) or None

    @field_validator("excluded_paths")
    @classmethod
    def _valid_excluded_paths(cls, value: list[str] | None) -> list[str] | None:
        if value and any(_has_relative_part(path) for path in value):
            raise field_format_error("Enter folder paths without . or .. parts.")
        return value
