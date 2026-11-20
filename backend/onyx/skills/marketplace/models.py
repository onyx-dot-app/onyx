from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, JsonValue, field_validator

from onyx.skills.models import PluginBundle, PluginFileEntry
from onyx.utils.github import GITHUB_REPOSITORY_COMPONENT_PATTERN


class GitHubMarketplaceConfig(BaseModel):
    """The repository of a GitHub marketplace. A None ref is the default
    branch. ``folder`` holds the .claude-plugin folder; None is the root."""

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
        return value

    @field_validator("folder")
    @classmethod
    def _validate_folder(cls, value: str | None) -> str | None:
        folder = (value or "").strip().strip("/")
        if not folder:
            return None
        if "\\" in folder or any(part in {"", ".", ".."} for part in folder.split("/")):
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
    """A marketplace entry whose plugin is in another GitHub repository.
    ``path`` is the plugin folder in that repository (git-subdir)."""

    model_config = ConfigDict(frozen=True)

    owner: str
    repo: str
    ref: str | None = None
    sha: str | None = None
    path: str | None = None


class ReadyPlugin(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["ok"] = "ok"
    entry_key: str
    path: str
    bundle: PluginBundle
    file_manifest: list[PluginFileEntry]
    # The git tree of the plugin folder; None when the tree was not read.
    tree_sha: str | None


class BlockedPlugin(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["blocked"] = "blocked"
    entry_key: str
    path: str | None
    reason: str


class UnsupportedPlugin(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["not_supported"] = "not_supported"
    entry_key: str
    reason: str


class RemotePlugin(BaseModel):
    """An entry the reader cannot build from the marketplace repository. The
    sync fetches its repository and builds it with ``build_entry_bundle``."""

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
    """A read that changes nothing: no plugin is added, changed or deleted."""

    model_config = ConfigDict(frozen=True)

    status: Literal["failed"] = "failed"
    reason: str


class MarketplaceArchive(BaseModel):
    model_config = ConfigDict(frozen=True)

    revision: str
    archive_bytes: bytes
    # Git tree of each folder by repository path, "" for the root. None when
    # GitHub cut the tree short.
    tree_shas: dict[str, str] | None


class MarketplaceEntryStatus(str, Enum):
    OK = "ok"
    BLOCKED = "blocked"
    NOT_SUPPORTED = "not_supported"


class MarketplaceEntryResult(BaseModel):
    """One entry of the last read, as stored in last_sync_result."""

    model_config = ConfigDict(frozen=True)

    key: str
    path: str | None
    status: MarketplaceEntryStatus
    reason: str | None = None


class MarketplaceSyncStatus(str, Enum):
    APPLIED = "applied"
    NEEDS_CONFIRMATION = "needs_confirmation"
    FAILED = "failed"


class CurrentSyncedPlugin(BaseModel):
    """A synced plugin as compare sees it."""

    model_config = ConfigDict(frozen=True)

    plugin_id: UUID
    entry_key: str
    name: str
    file_manifest: list[PluginFileEntry] | None


class SyncPlan(BaseModel):
    """What one sync writes. ``create`` and ``add_version`` hold entry keys."""

    model_config = ConfigDict(frozen=True)

    create: list[str]
    add_version: dict[str, UUID]
    delete_plugin_ids: list[UUID]
    results: list[MarketplaceEntryResult]
    needs_confirmation: bool


class MarketplaceSyncResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: MarketplaceSyncStatus
    created: list[UUID] = []
    versioned: list[UUID] = []
    deleted: list[UUID] = []
    blocked: list[str] = []
    cleanup_file_ids: list[str] = []
    affected_user_ids: set[UUID] = set()
