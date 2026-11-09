from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from onyx.utils.github import (
    normalize_github_folder,
    validate_github_repository_component,
)

MARKETPLACE_LOGIN_ERROR = "Marketplace login is unavailable. Replace the login with an active user connected to GitHub."


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


class MarketplaceArchive(BaseModel):
    revision: str
    archive_bytes: bytes
    folder: str | None
