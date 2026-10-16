from typing import Literal

from pydantic import BaseModel, Field

from onyx.server.manage.api_token.models import ApiTokenInput
from shared_configs.enums import TracingProviderType


class TracingProviderView(BaseModel):
    provider_type: TracingProviderType
    connected: bool
    # "db" (configured in the UI), "env" (legacy env vars), or "none".
    source: Literal["db", "env", "none"]
    enabled: bool
    config: dict[str, str] = Field(default_factory=dict)
    masked_api_key: str | None = None
    api_token_id: int | None = None


class TracingProviderUpsertRequest(BaseModel):
    provider_type: TracingProviderType
    config: dict[str, str] | None = None
    api_key: ApiTokenInput | None = Field(
        default=None,
        description="A new key, or the id of a saved key. An edit that keeps the "
        "key sends the id of the key it already has. None clears the key.",
    )
    enabled: bool = True


class TracingProviderTestRequest(BaseModel):
    provider_type: TracingProviderType
    api_key: ApiTokenInput | None = Field(
        default=None,
        description="The key to test: a new key, or the id of a saved key.",
    )
    config: dict[str, str] | None = None
