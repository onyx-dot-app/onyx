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
    PERSONAL = "personal"
    COMPANY = "company"


class MarketplaceSourceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repository: str = Field(min_length=1, max_length=512)
    folder: str | None = Field(default=None, max_length=1024)
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
    name: str | None
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
    plugin_id: UUID | None


class MarketplacePluginView(BaseModel):
    id: UUID
    name: str


class MarketplaceDetail(MarketplaceSummary):
    entries: list[MarketplaceEntryView]
    plugins: list[MarketplacePluginView]


class MarketplaceList(BaseModel):
    marketplaces: list[MarketplaceSummary]
