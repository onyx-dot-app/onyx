from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from onyx.db.enums import SkillInstallationPolicy, SkillSharePermission
from onyx.utils.github import (
    normalize_github_folder,
    validate_github_repository_component,
)

MARKETPLACE_LOGIN_ERROR = "Marketplace login is unavailable. Replace the login with an active user connected to GitHub."


class MarketplaceSyncStatus(StrEnum):
    APPLIED = "applied"
    FAILED = "failed"
    NEEDS_CONFIRMATION = "needs_confirmation"


class MarketplaceProvider(StrEnum):
    GITHUB = "github"


class GitHubMarketplaceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    owner: str
    repo: str
    folder: str | None = None
    ref: str = Field(min_length=1)

    @field_validator("owner", "repo")
    @classmethod
    def validate_repository_component(cls, value: str) -> str:
        return validate_github_repository_component(value)

    @field_validator("folder")
    @classmethod
    def validate_folder(cls, value: str | None) -> str | None:
        return normalize_github_folder(value)

    @field_validator("ref")
    @classmethod
    def validate_ref(cls, value: str) -> str:
        if (
            value == "@"
            or ".." in value
            or "@{" in value
            or value.endswith(".")
            or any(
                ord(char) < 33 or ord(char) == 127 or char in "~^:?*[\\"
                for char in value
            )
            or any(
                not part or part.startswith(".") or part.endswith(".lock")
                for part in value.split("/")
            )
        ):
            raise ValueError("Use a branch, tag, or full commit SHA.")
        return value


class GitHubHookConfig(BaseModel):
    url: str


class GitHubHook(BaseModel):
    id: int
    config: GitHubHookConfig


class GitHubRef(BaseModel):
    ref: str


class GitHubRepository(BaseModel):
    default_branch: str


class MarketplaceArchive(BaseModel):
    revision: str
    archive_bytes: bytes
    folder: str | None


class MarketplaceRetirementProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    revision: str
    skill_ids: tuple[UUID, ...]
    approved: bool = False


class ReconciliationResult(BaseModel):
    status: Literal["applied", "failed", "needs_confirmation"]
    reason: str | None = None
    changed_skill_ids: list[UUID] = Field(default_factory=list)
    retired_skill_ids: list[UUID] = Field(default_factory=list)
    blocked_entries: dict[str, str] = Field(default_factory=dict)
    cleanup_file_ids: set[str] = Field(default_factory=set)
    affected_user_ids: set[UUID] = Field(default_factory=set)


class MarketplaceGroupAccess(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_group_id: int
    permission: SkillSharePermission
    installation_policy: SkillInstallationPolicy | None


class MarketplaceManagementSnapshot(BaseModel):
    """Safe internal read data; never contains login credentials or webhook secrets."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    provider: MarketplaceProvider
    provider_config: GitHubMarketplaceConfig
    owner_user_id: UUID | None
    login_user_id: UUID | None
    public_permission: SkillSharePermission | None
    installation_policy: SkillInstallationPolicy
    group_shares: list[MarketplaceGroupAccess]
    sync_requested: bool
    sync_pending: bool = False
    sync_status: MarketplaceSyncStatus | None
    last_synced_revision: str | None
    last_synced_at: datetime | None
    last_error: str | None
    blocked_entries: dict[str, str]
    retirement_proposal: MarketplaceRetirementProposal | None
    live_skill_count: int = 0
    retired_skill_count: int = 0


class MarketplaceManagedSkill(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    current_version_id: UUID | None
    retired_at: datetime | None
    follows_marketplace_access: bool


class MarketplaceManagementDetail(BaseModel):
    marketplace: MarketplaceManagementSnapshot
    skills: list[MarketplaceManagedSkill]


class MarketplaceRemovalResult(BaseModel):
    cleanup_file_ids: set[str]
    affected_user_ids: set[UUID]
