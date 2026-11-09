"""Public marketplace input and preview data, without bundles or credentials."""

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from onyx.server.features.skill.models import SkillShareRequest
from onyx.skills.marketplace.models import GitHubMarketplaceConfig, MarketplaceProvider
from onyx.skills.marketplace.read_models import BlockedSkill, UnsupportedPlugin
from onyx.skills.models import GITHUB_SKILL_MAX_COUNT


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


class MarketplaceAccessRequest(SkillShareRequest):
    user_shares: None = None


class MarketplaceCreateRequest(MarketplaceSourceRequest):
    name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
    ]
    access: MarketplaceAccessRequest | None = None

    @model_validator(mode="after")
    def company_defaults_only(self) -> Self:
        if self.personal and self.access is not None:
            raise ValueError("Personal marketplace skills are shared individually.")
        return self


class MarketplaceConfirmationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision: str = Field(min_length=1)
    skill_ids: list[UUID] = Field(min_length=1, max_length=GITHUB_SKILL_MAX_COUNT)


class MarketplaceCompletePreview(BaseModel):
    status: Literal["complete"] = "complete"
    revision: str
    entries: list[MarketplaceReadyPreview | BlockedSkill | UnsupportedPlugin]


class MarketplaceFailedPreview(BaseModel):
    status: Literal["failed"] = "failed"
    revision: str
    reason: str
