from typing import Any

from pydantic import BaseModel
from pydantic import Field

from shared_configs.enums import WebContentProviderType
from shared_configs.enums import WebSearchProviderType


class WebSearchProviderView(BaseModel):
    id: int
    name: str
    provider_type: WebSearchProviderType
    is_active: bool
    config: dict[str, str] | None
    has_api_key: bool = Field(
        default=False,
        description="Indicates whether an API key is stored for this provider.",
    )


class WebSearchProviderUpsertRequest(BaseModel):
    id: int | None = Field(default=None, description="Existing provider ID to update.")
    name: str
    provider_type: WebSearchProviderType
    config: dict[str, str] | None = None
    api_key: str | None = Field(
        default=None,
        description="API key for the provider. Only required when creating or updating credentials.",
    )
    api_key_changed: bool = Field(
        default=False,
        description="Set to true when providing a new API key for an existing provider.",
    )
    activate: bool = Field(
        default=False,
        description="If true, sets this provider as the active one after upsert.",
    )


class WebContentProviderView(BaseModel):
    id: int
    name: str
    provider_type: WebContentProviderType
    is_active: bool
    config: dict[str, str] | None
    has_api_key: bool = Field(default=False)


class WebContentProviderUpsertRequest(BaseModel):
    id: int | None = None
    name: str
    provider_type: WebContentProviderType
    config: dict[str, str] | None = None
    api_key: str | None = None
    api_key_changed: bool = False
    activate: bool = False


class WebSearchProviderTestRequest(BaseModel):
    provider_type: WebSearchProviderType
    api_key: str | None = None
    config: dict[str, Any] | None = None


class WebContentProviderTestRequest(BaseModel):
    provider_type: WebContentProviderType
    api_key: str | None = None
    config: dict[str, Any] | None = None
