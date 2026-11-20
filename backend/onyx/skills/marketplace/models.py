from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, JsonValue, field_validator

from onyx.skills.models import PluginBundle, PluginFileEntry
from onyx.utils.github import GITHUB_REPOSITORY_COMPONENT_PATTERN


class GitHubMarketplaceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    owner: str
    repo: str
    folder: str | None = None
    ref: str | None = None

    @field_validator("owner", "repo")
    @classmethod
    def _validate_component(cls, value: str) -> str:
        if value in {".", ".."} or not GITHUB_REPOSITORY_COMPONENT_PATTERN.fullmatch(
            value
        ):
            raise ValueError("Use a valid GitHub owner and repository name.")
        # GitHub names ignore case, so one form lets the unique indexes match.
        return value.lower()

    @field_validator("folder")
    @classmethod
    def _validate_folder(cls, value: str | None) -> str | None:
        folder = (value or "").strip().strip("/")
        if not folder:
            return None
        if (
            "\\" in folder
            or any(ord(char) < 32 or ord(char) == 127 for char in folder)
            or any(part in {"", ".", ".."} for part in folder.split("/"))
        ):
            raise ValueError(
                "Use a folder path in the repository, with no '.' or '..'."
            )
        return folder

    @field_validator("ref")
    @classmethod
    def _validate_ref(cls, value: str | None) -> str | None:
        ref = (value or "").strip()
        if not ref:
            return None
        if (
            ref == "@"
            or ".." in ref
            or "@{" in ref
            or ref.endswith(".")
            or any(
                ord(char) < 33 or ord(char) == 127 or char in "~^:?*[\\" for char in ref
            )
            or any(
                not part or part.startswith(".") or part.endswith(".lock")
                for part in ref.split("/")
            )
        ):
            raise ValueError("Use a branch, tag or full commit SHA.")
        return ref

    @property
    def repository(self) -> str:
        return f"{self.owner}/{self.repo}"


class GitHubRepoSource(BaseModel):
    model_config = ConfigDict(frozen=True)

    owner: str
    repo: str
    ref: str | None = None
    sha: str | None = None
    path: str | None = None

    @field_validator("owner", "repo")
    @classmethod
    def _lower(cls, value: str) -> str:
        # GitHub names ignore case, so one form groups the same repository.
        return value.lower()


class ReadyPlugin(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["ok"] = "ok"
    entry_key: str
    path: str
    bundle: PluginBundle
    file_manifest: list[PluginFileEntry]


class MarketplaceReasonCode(str, Enum):
    """A reason the web translates. ``reason`` keeps the English text."""

    SKILLS_AND_MCP_ONLY = "skills_and_mcp_only"
    EXTERNAL_REPOSITORY_LIMIT = "external_repository_limit"
    EXTERNAL_REPOSITORY_LIMIT_WITHOUT_LOGIN = "external_repository_limit_without_login"


class BlockedPlugin(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["blocked"] = "blocked"
    entry_key: str
    path: str | None
    reason: str
    reason_code: MarketplaceReasonCode | None = None


class UnsupportedPlugin(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["not_supported"] = "not_supported"
    entry_key: str
    reason: str
    reason_code: MarketplaceReasonCode | None = None


class RemotePlugin(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["remote"] = "remote"
    entry_key: str
    source: GitHubRepoSource
    entry: dict[str, JsonValue]


MarketplaceEntry = ReadyPlugin | BlockedPlugin | UnsupportedPlugin | RemotePlugin


class CompleteMarketplace(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["complete"] = "complete"
    name: str
    entries: tuple[MarketplaceEntry, ...]


class FailedMarketplace(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["failed"] = "failed"
    reason: str


class MarketplaceEntryStatus(str, Enum):
    OK = "ok"
    BLOCKED = "blocked"
    NOT_SUPPORTED = "not_supported"


class MarketplaceEntryResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str
    path: str | None
    status: MarketplaceEntryStatus
    reason: str | None = None
    reason_code: MarketplaceReasonCode | None = None


class MarketplaceSyncStatus(str, Enum):
    APPLIED = "applied"
    FAILED = "failed"


class CurrentSyncedPlugin(BaseModel):
    model_config = ConfigDict(frozen=True)

    plugin_id: UUID
    name: str
    file_manifest: list[PluginFileEntry] | None


class SyncPlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    create: list[str]
    add_version: dict[str, UUID]
    delete_plugin_ids: list[UUID]
    results: list[MarketplaceEntryResult]


class MarketplaceSyncResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: MarketplaceSyncStatus
    created: list[UUID] = []
    versioned: list[UUID] = []
    deleted: list[UUID] = []
    blocked: list[str] = []
    cleanup_file_ids: list[str] = []
    affected_user_ids: set[UUID] = set()
    # Needs of the plugins that the sync turned on for a personal owner.


class MarketplaceRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    revision: str
    name: str | None
    failure: str | None
    entries: list[ReadyPlugin | BlockedPlugin | UnsupportedPlugin]
