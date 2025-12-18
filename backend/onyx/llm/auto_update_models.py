"""Pydantic models for GitHub-hosted Auto LLM configuration."""

from datetime import datetime

from pydantic import BaseModel


class GitHubModelConfig(BaseModel):
    """Configuration for a single model in the GitHub config."""

    name: str
    display_name: str | None = None
    max_input_tokens: int | None = None
    supports_image_input: bool = False
    supports_reasoning: bool = False
    is_visible: bool = True  # Controls visibility in Auto mode


class GitHubProviderConfig(BaseModel):
    """Configuration for a single provider in the GitHub config."""

    models: list[GitHubModelConfig]
    default_model: str | None = None
    fast_default_model: str | None = None


class GitHubLLMConfig(BaseModel):
    """Root configuration object fetched from GitHub."""

    version: str
    updated_at: datetime
    providers: dict[str, GitHubProviderConfig]
