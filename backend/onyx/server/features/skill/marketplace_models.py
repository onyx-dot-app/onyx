import datetime
from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from onyx.db.enums import PluginInstallationPolicy
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.integrations.models import PluginNeedView
from onyx.server.models import MinimalUserSnapshot
from onyx.skills.marketplace.models import (
    GitHubMarketplaceConfig,
    MarketplaceEntryStatus,
)
from onyx.utils.github import parse_github_source


class MarketplaceScope(str, Enum):
    # Owned by the user who adds it. Its plugins are the owner's.
    PERSONAL = "personal"
    # Seen by the organization. Needs organization-wide manage:plugins.
    COMPANY = "company"


class MarketplaceSourceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # "owner/repo" or https://github.com/owner/repo.
    repository: str = Field(min_length=1, max_length=512)
    # The folder that holds .claude-plugin/marketplace.json. None: the root.
    folder: str | None = Field(default=None, max_length=1024)
    # A branch, tag or commit. None: the default branch.
    ref: str | None = Field(default=None, max_length=255)

    def to_config(self) -> GitHubMarketplaceConfig:
        source = parse_github_source(self.repository)
        if source.tree_tail:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "Enter the repository URL. Give the folder and the branch in "
                "their own fields.",
            )
        try:
            return GitHubMarketplaceConfig(
                owner=source.owner, repo=source.repo, folder=self.folder, ref=self.ref
            )
        except ValueError as exc:
            raise OnyxError(OnyxErrorCode.INVALID_INPUT, str(exc)) from exc


class MarketplaceCreateRequest(MarketplaceSourceRequest):
    scope: MarketplaceScope
    # Company only. None: Available.
    default_installation_policy: PluginInstallationPolicy | None = None


class MarketplaceConfirmDeletesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The revision the detail shows in pending_delete_revision.
    revision: str = Field(min_length=1, max_length=40)


class MarketplaceDefaultAccessRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    installation_policy: PluginInstallationPolicy


class MarketplacePreviewSkill(BaseModel):
    name: str
    description: str


class MarketplacePreviewEntry(BaseModel):
    key: str
    path: str | None
    status: MarketplaceEntryStatus
    # Why the entry is blocked or not supported.
    reason: str | None
    # The plugin.json fields; None unless status is ok.
    name: str | None = None
    description: str | None = None
    version: str | None = None
    skills: list[MarketplacePreviewSkill] = Field(default_factory=list)
    needs: list[PluginNeedView] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class MarketplacePreviewResponse(BaseModel):
    repository: str
    folder: str | None
    ref: str | None
    revision: str
    status: Literal["complete", "failed"]
    # The marketplace.json name; None when the read failed.
    name: str | None
    # Why the read failed; None when it completed.
    reason: str | None
    entries: list[MarketplacePreviewEntry]


class MarketplaceSummary(BaseModel):
    id: UUID
    name: str
    scope: MarketplaceScope
    repository: str
    folder: str | None
    ref: str | None
    default_installation_policy: PluginInstallationPolicy
    # The user whose GitHub connection reads the repository; None when gone.
    login_user: MinimalUserSnapshot | None
    plugin_count: int
    last_synced_at: datetime.datetime | None
    last_synced_revision: str | None
    last_error: str | None
    # A sync is asked for and has not started yet.
    sync_requested: bool
    # A sync waits for a user to confirm its deletes.
    needs_confirmation: bool
    created_at: datetime.datetime


class MarketplaceEntryView(BaseModel):
    key: str
    path: str | None
    status: MarketplaceEntryStatus
    reason: str | None
    # The plugin of the entry, if it has one.
    plugin_id: UUID | None
    plugin_name: str | None


class MarketplacePendingDelete(BaseModel):
    plugin_id: UUID
    entry_key: str
    name: str


class MarketplaceDetail(MarketplaceSummary):
    # One item per entry of the last read.
    entries: list[MarketplaceEntryView]
    # Send this back to confirm-deletes. None when nothing waits.
    pending_delete_revision: str | None
    pending_deletes: list[MarketplacePendingDelete]


class MarketplaceList(BaseModel):
    marketplaces: list[MarketplaceSummary]
