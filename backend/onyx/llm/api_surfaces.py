"""Wire protocols ("API surfaces") that provider endpoints speak.

Routing depends on the surface rather than the provider: which LiteLLM provider
to impersonate, whether to coerce the base URL to `/v1`, and how to address the
model. A gateway can expose several surfaces, with the admin picking one.
"""

from enum import Enum

from onyx.llm.constants import LlmProviderNames
from onyx.llm.well_known_providers.constants import (
    BIFROST_API_MODE_CHAT_COMPLETIONS,
    BIFROST_API_MODE_CONFIG_KEY,
    BIFROST_API_MODE_RESPONSES,
    BIFROST_DEFAULT_API_MODE,
    PORTKEY_API_MODE_CHAT_COMPLETIONS,
    PORTKEY_API_MODE_CONFIG_KEY,
    PORTKEY_API_MODE_MESSAGES,
    PORTKEY_API_MODE_RESPONSES,
    PORTKEY_DEFAULT_API_MODE,
)


class LlmApiSurface(str, Enum):
    OPENAI_CHAT_COMPLETIONS = "openai_chat_completions"
    # Reached via LiteLLM's completions->responses bridge (a `responses/` prefix).
    OPENAI_RESPONSES = "openai_responses"
    # LiteLLM appends /v1/messages to the base, so the base must stay bare.
    ANTHROPIC_MESSAGES = "anthropic_messages"


# Share the `/v1` base coercion and the placeholder-api-key workaround.
OPENAI_COMPATIBLE_SURFACES = frozenset(
    {LlmApiSurface.OPENAI_CHAT_COMPLETIONS, LlmApiSurface.OPENAI_RESPONSES}
)

_STATIC_SURFACES: dict[str, LlmApiSurface] = {
    LlmProviderNames.OPENAI_COMPATIBLE: LlmApiSurface.OPENAI_CHAT_COMPLETIONS,
    LlmProviderNames.NEBIUS_TOKENFACTORY: LlmApiSurface.OPENAI_CHAT_COMPLETIONS,
}

# Admin-selected surfaces: {provider: (config_key, {stored value: surface}, default)}
_SELECTABLE_SURFACES: dict[str, tuple[str, dict[str, LlmApiSurface], str]] = {
    LlmProviderNames.PORTKEY: (
        PORTKEY_API_MODE_CONFIG_KEY,
        {
            PORTKEY_API_MODE_CHAT_COMPLETIONS: LlmApiSurface.OPENAI_CHAT_COMPLETIONS,
            PORTKEY_API_MODE_RESPONSES: LlmApiSurface.OPENAI_RESPONSES,
            PORTKEY_API_MODE_MESSAGES: LlmApiSurface.ANTHROPIC_MESSAGES,
        },
        PORTKEY_DEFAULT_API_MODE,
    ),
    # Bifrost's Anthropic-compatible surface lives under a different path
    # prefix (/anthropic), so only the OpenAI-compatible modes are offered.
    LlmProviderNames.BIFROST: (
        BIFROST_API_MODE_CONFIG_KEY,
        {
            BIFROST_API_MODE_CHAT_COMPLETIONS: LlmApiSurface.OPENAI_CHAT_COMPLETIONS,
            BIFROST_API_MODE_RESPONSES: LlmApiSurface.OPENAI_RESPONSES,
        },
        BIFROST_DEFAULT_API_MODE,
    ),
}

# UI form state, not credentials — exempt from environment injection.
SURFACE_SELECTION_CONFIG_KEYS: frozenset[str] = frozenset(
    config_key for config_key, _, _ in _SELECTABLE_SURFACES.values()
)


def resolve_api_surface(
    model_provider: str, custom_config: dict[str, str] | None
) -> LlmApiSurface | None:
    """None when the provider is reached through LiteLLM's own integration
    (Bedrock, Vertex, native Anthropic, ...)."""
    selectable = _SELECTABLE_SURFACES.get(model_provider)
    if selectable is not None:
        config_key, by_value, default = selectable
        chosen = (custom_config or {}).get(config_key) or default
        return by_value.get(chosen, by_value[default])
    return _STATIC_SURFACES.get(model_provider)
