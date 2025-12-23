"""Pydantic models for GitHub-hosted Auto LLM configuration."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel
from pydantic import field_validator


class GitHubModelConfig(BaseModel):
    """Configuration for a single model in the GitHub config."""

    name: str
    display_name: str | None = None


class GitHubProviderConfig(BaseModel):
    """Configuration for a single provider in the GitHub config.

    Schema matches the plan:
    - default_model: The default model config (can be string or object with name)
    - additional_visible_models: List of additional visible model configs
    """

    default_model: GitHubModelConfig
    additional_visible_models: list[GitHubModelConfig] = []

    @field_validator("default_model", mode="before")
    @classmethod
    def normalize_default_model(cls, v: Any) -> dict[str, Any]:
        """Allow default_model to be a string (model name) or object."""
        if isinstance(v, str):
            return {"name": v}
        return v


class GitHubLLMConfig(BaseModel):
    """Root configuration object fetched from GitHub."""

    version: str
    updated_at: datetime
    providers: dict[str, GitHubProviderConfig]
