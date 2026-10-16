from typing import Any

from pydantic import BaseModel, Field

from onyx.server.manage.api_token.models import ApiTokenInput
from onyx.tools.tool_implementations.web_search.models import WebContentProviderConfig
from shared_configs.enums import WebContentProviderType, WebSearchProviderType


class WebSearchProviderView(BaseModel):
    id: int
    name: str
    provider_type: WebSearchProviderType
    is_active: bool
    config: dict[str, str] | None
    masked_api_key: str | None = Field(
        default=None,
        description="Masked API key for display (e.g. 'sk-a...z456'). None means no key stored.",
    )
    api_token_id: int | None = Field(
        default=None, description="ID of the saved API key this provider uses."
    )


class WebSearchProviderUpsertRequest(BaseModel):
    id: int | None = Field(default=None, description="Existing provider ID to update.")
    name: str
    provider_type: WebSearchProviderType
    config: dict[str, str] | None = None
    api_key: ApiTokenInput | None = Field(
        default=None,
        description="A new key, or the id of a saved key. An edit that keeps the "
        "key sends the id of the key it already has. None clears the key.",
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
    config: WebContentProviderConfig | None
    masked_api_key: str | None = None
    api_token_id: int | None = None


class WebContentProviderUpsertRequest(BaseModel):
    id: int | None = None
    name: str
    provider_type: WebContentProviderType
    config: WebContentProviderConfig | None = None
    api_key: ApiTokenInput | None = None
    activate: bool = False


class WebSearchProviderTestRequest(BaseModel):
    provider_type: WebSearchProviderType
    api_key: ApiTokenInput | None = Field(
        default=None,
        description="The key to test: a new key, or the id of a saved key.",
    )
    config: dict[str, Any] | None = None


class WebContentProviderTestRequest(BaseModel):
    provider_type: WebContentProviderType
    api_key: ApiTokenInput | None = Field(
        default=None,
        description="The key to test: a new key, or the id of a saved key.",
    )
    config: WebContentProviderConfig
