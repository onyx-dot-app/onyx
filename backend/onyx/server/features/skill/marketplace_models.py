import datetime
from collections.abc import Callable
from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from onyx.db.enums import PluginInstallationPolicy
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.integrations.models import PluginNeedView
from onyx.server.models import MinimalUserSnapshot
from onyx.skills.marketplace.models import (
    GitHubMarketplaceConfig,
    MarketplaceEntryStatus,
    MarketplaceReasonCode,
)
from onyx.utils.github import GitHubRevision, GitHubSource, parse_github_source


class MarketplaceScope(str, Enum):
    PERSONAL = "personal"
    COMPANY = "company"


class MarketplaceSourceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repository: str = Field(min_length=1, max_length=512)
    folder: str | None = Field(default=None, max_length=1024)
    ref: str | None = Field(default=None, max_length=255)

    def to_config(
        self, resolve_tree: Callable[[GitHubSource], GitHubRevision] | None = None
    ) -> GitHubMarketplaceConfig:
        """A folder URL (.../tree/<ref>/<folder>) fills the empty ref and
        folder; ``resolve_tree`` splits a ref with '/' from the folder."""
        source = parse_github_source(self.repository)
        folder, ref = self.folder, self.ref
        if source.tree_tail:
            if (folder or "").strip() or (ref or "").strip():
                raise OnyxError(
                    OnyxErrorCode.INVALID_INPUT,
                    "Enter the repository URL. Give the folder and the branch in "
                    "their own fields.",
                )
            if len(source.tree_tail) == 1:
                folder = None
            elif resolve_tree is None:
                raise RuntimeError("Bug: a folder URL needs a tree resolver.")
            else:
                folder = resolve_tree(source).subpath
            folder_parts = len(folder.split("/")) if folder else 0
            ref = "/".join(source.tree_tail[: len(source.tree_tail) - folder_parts])
        try:
            return GitHubMarketplaceConfig(
                owner=source.owner, repo=source.repo, folder=folder, ref=ref
            )
        except ValidationError as exc:
            message = str(exc.errors()[0]["msg"]).removeprefix("Value error, ")
            raise OnyxError(OnyxErrorCode.INVALID_INPUT, message) from exc


class MarketplaceCreateRequest(MarketplaceSourceRequest):
    scope: MarketplaceScope
    # The name the preview read; the first sync replaces it.
    name: str | None = Field(default=None, max_length=255)
    default_installation_policy: PluginInstallationPolicy | None = None


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
    reason: str | None
    reason_code: MarketplaceReasonCode | None = None
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
    name: str | None
    reason: str | None
    entries: list[MarketplacePreviewEntry]
    # The caller already has this source as a personal marketplace, or the
    # organization has it as a company marketplace.
    added_personal: bool = False
    added_company: bool = False


class MarketplaceSummary(BaseModel):
    id: UUID
    name: str
    scope: MarketplaceScope
    repository: str
    folder: str | None
    ref: str | None
    # None for a personal marketplace, which has no default.
    default_installation_policy: PluginInstallationPolicy | None
    # False for a member who sees a company marketplace read-only.
    can_manage: bool
    login_user: MinimalUserSnapshot | None
    plugin_count: int
    last_synced_at: datetime.datetime | None
    last_synced_revision: str | None
    last_error: str | None
    syncing: bool
    created_at: datetime.datetime


class MarketplaceEntryView(BaseModel):
    key: str
    path: str | None
    status: MarketplaceEntryStatus
    reason: str | None
    reason_code: MarketplaceReasonCode | None = None
    plugin_id: UUID | None


class MarketplacePluginView(BaseModel):
    id: UUID
    name: str


class MarketplaceDetail(MarketplaceSummary):
    # False when the login user has no working GitHub connection, so the sync
    # reads only public repositories.
    login_has_github: bool
    entries: list[MarketplaceEntryView]
    plugins: list[MarketplacePluginView]


class MarketplaceList(BaseModel):
    marketplaces: list[MarketplaceSummary]
