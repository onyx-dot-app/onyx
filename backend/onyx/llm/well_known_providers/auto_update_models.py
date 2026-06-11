"""Pydantic models for GitHub-hosted Auto LLM configuration."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel
from pydantic import field_validator

from onyx.llm.well_known_providers.models import SimpleKnownModel


class LLMProviderRecommendation(BaseModel):
    """Configuration for a single provider in the GitHub config.

    Schema matches the plan:
    - default_model: The default model config (can be string or object with name)
    - additional_visible_models: List of additional visible model configs
    """

    default_model: SimpleKnownModel
    additional_visible_models: list[SimpleKnownModel] = []

    @field_validator("default_model", mode="before")
    @classmethod
    def normalize_default_model(cls, v: Any) -> dict[str, Any]:
        """Allow default_model to be a string (model name) or object."""
        if isinstance(v, str):
            return {"name": v}
        return v


class LLMRecommendations(BaseModel):
    """Root configuration object fetched from GitHub."""

    version: str
    updated_at: datetime
    providers: dict[str, LLMProviderRecommendation]

    def get_visible_models(self, provider_name: str) -> list[SimpleKnownModel]:
        """Default model first, then additional models, deduped by name. The
        default is often repeated in additional_visible_models (where it carries
        a display name), so keep the entry that has one."""
        provider_config = self.providers.get(provider_name)
        if provider_config is None:
            return []
        by_name: dict[str, SimpleKnownModel] = {}
        for model in [
            provider_config.default_model,
            *provider_config.additional_visible_models,
        ]:
            existing = by_name.get(model.name)
            if existing is None or (model.display_name and not existing.display_name):
                by_name[model.name] = model
        return list(by_name.values())

    def get_default_model(self, provider_name: str) -> SimpleKnownModel | None:
        """Get the default model for a provider."""
        if provider_name in self.providers:
            provider_config = self.providers[provider_name]
            return provider_config.default_model
        return None
