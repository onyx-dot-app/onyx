from pydantic import BaseModel
from pydantic import Field

from shared_configs.enums import TracingProviderType


class TracingProviderView(BaseModel):
    provider_type: TracingProviderType
    connected: bool
    # "db" (configured in the UI), "env" (legacy env vars), or "none".
    source: str
    enabled: bool
    config: dict[str, str] = Field(default_factory=dict)
    masked_api_key: str | None = None


class TracingProviderUpsertRequest(BaseModel):
    provider_type: TracingProviderType
    config: dict[str, str] | None = None
    api_key: str | None = None
    api_key_changed: bool = Field(
        default=False,
        description="Set to true when providing a new key for an existing provider.",
    )
    enabled: bool = True


class TracingProviderTestRequest(BaseModel):
    provider_type: TracingProviderType
    api_key: str | None = None
    use_stored_key: bool = Field(
        default=False,
        description="If true, validate the stored key instead of `api_key`.",
    )
    config: dict[str, str] | None = None
