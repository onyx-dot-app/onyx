"""Public marketplace input and preview data, without bundles or credentials."""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from onyx.skills.marketplace.models import GitHubMarketplaceConfig, MarketplaceProvider
from onyx.skills.marketplace.read_models import BlockedSkill, UnsupportedPlugin


class MarketplaceSourceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: MarketplaceProvider = MarketplaceProvider.GITHUB
    provider_config: GitHubMarketplaceConfig
    personal: bool = True


class MarketplaceReadyPreview(BaseModel):
    status: Literal["ok"] = "ok"
    entry_key: str
    path: str
    name: str
    description: str


class MarketplaceCompletePreview(BaseModel):
    status: Literal["complete"] = "complete"
    revision: str
    entries: list[MarketplaceReadyPreview | BlockedSkill | UnsupportedPlugin]


class MarketplaceFailedPreview(BaseModel):
    status: Literal["failed"] = "failed"
    revision: str
    reason: str
