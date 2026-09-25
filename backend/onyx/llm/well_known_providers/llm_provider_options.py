import json
import pathlib
import threading
import time

from onyx.llm.api_surfaces import resolve_api_surface
from onyx.llm.constants import (
    PROVIDER_DISPLAY_NAMES,
    WELL_KNOWN_PROVIDER_NAMES,
    LlmProviderNames,
)
from onyx.llm.model_capabilities import (
    get_max_input_tokens,
    supported_reasoning_efforts,
)
from onyx.llm.utils import model_supports_image_input
from onyx.llm.well_known_providers.auto_update_models import LLMRecommendations
from onyx.llm.well_known_providers.auto_update_service import (
    fetch_llm_recommendations_from_github,
)
from onyx.llm.well_known_providers.constants import (
    ANTHROPIC_PROVIDER_NAME,
    AZURE_PROVIDER_NAME,
    BEDROCK_PROVIDER_NAME,
    BIFROST_PROVIDER_NAME,
    LITELLM_PROXY_PROVIDER_NAME,
    LM_STUDIO_PROVIDER_NAME,
    NEBIUS_TOKENFACTORY_PROVIDER_NAME,
    OLLAMA_PROVIDER_NAME,
    OPENAI_COMPATIBLE_PROVIDER_NAME,
    OPENAI_PROVIDER_NAME,
    OPENROUTER_PROVIDER_NAME,
    PORTKEY_PROVIDER_NAME,
    VERCEL_AI_GATEWAY_PROVIDER_NAME,
    VERTEXAI_PROVIDER_NAME,
)
from onyx.llm.well_known_providers.models import WellKnownLLMProviderDescriptor
from onyx.server.manage.llm.models import ModelConfigurationView
from onyx.utils.logger import setup_logger

logger = setup_logger()

_RECOMMENDATIONS_CACHE_TTL_SECONDS = 300
_recommendations_cache_lock = threading.Lock()
_cached_recommendations: LLMRecommendations | None = None
_cached_recommendations_time: float = 0.0


def _get_provider_to_models_map() -> dict[str, list[str]]:
    """Lazy-load provider model mappings.

    Dynamic providers (Bedrock, Ollama, OpenRouter) return empty lists here
    because their models are fetched directly from the source API, which is
    more up-to-date than a static catalog.
    """
    return {
        OPENAI_PROVIDER_NAME: get_openai_model_names(),
        BEDROCK_PROVIDER_NAME: [],  # Dynamic - fetched from AWS API
        ANTHROPIC_PROVIDER_NAME: get_anthropic_model_names(),
        VERTEXAI_PROVIDER_NAME: get_vertexai_model_names(),
        OLLAMA_PROVIDER_NAME: [],  # Dynamic - fetched from Ollama API
        LM_STUDIO_PROVIDER_NAME: [],  # Dynamic - fetched from LM Studio API
        OPENROUTER_PROVIDER_NAME: [],  # Dynamic - fetched from OpenRouter API
        LITELLM_PROXY_PROVIDER_NAME: [],  # Dynamic - fetched from LiteLLM proxy API
        BIFROST_PROVIDER_NAME: [],  # Dynamic - fetched from Bifrost API
        OPENAI_COMPATIBLE_PROVIDER_NAME: [],  # Dynamic - fetched from OpenAI-compatible API
        NEBIUS_TOKENFACTORY_PROVIDER_NAME: [],  # Dynamic - fetched from /v1/models
        PORTKEY_PROVIDER_NAME: [],  # Dynamic - fetched from the Portkey gateway
        VERCEL_AI_GATEWAY_PROVIDER_NAME: [],  # Dynamic - fetched from the public catalog
    }


def _load_bundled_recommendations() -> LLMRecommendations:
    json_path = pathlib.Path(__file__).parent / "recommended-models.json"
    with open(json_path, "r") as f:
        json_config = json.load(f)
    return LLMRecommendations.model_validate(json_config)


def get_recommendations() -> LLMRecommendations:
    """Get the recommendations, with an in-memory cache to avoid
    hitting GitHub on every API request."""
    global _cached_recommendations, _cached_recommendations_time

    now = time.monotonic()
    if (
        _cached_recommendations is not None
        and (now - _cached_recommendations_time) < _RECOMMENDATIONS_CACHE_TTL_SECONDS
    ):
        return _cached_recommendations

    with _recommendations_cache_lock:
        # Double-check after acquiring lock
        if (
            _cached_recommendations is not None
            and (time.monotonic() - _cached_recommendations_time)
            < _RECOMMENDATIONS_CACHE_TTL_SECONDS
        ):
            return _cached_recommendations

        recommendations_from_github = fetch_llm_recommendations_from_github()
        result = recommendations_from_github or _load_bundled_recommendations()

        _cached_recommendations = result
        _cached_recommendations_time = time.monotonic()
        return result


def get_openai_model_names() -> list[str]:
    """Get OpenAI model names from the vendored model catalog."""
    import re

    from onyx.llm import model_catalog

    # TODO: remove these lists once we have a comprehensive model configuration page
    # The ideal flow should be: fetch all available models --> filter by type
    # --> allow user to modify filters and select models based on current context
    # NOTE: deprecated-but-still-served models (e.g. gpt-3.5-turbo, gpt-4) are
    # intentionally kept — the catalog only contains models OpenAI still serves.
    excluded_terms = {
        "embed",
        "audio",
        "tts",
        "whisper",
        "dall-e",
        "image",
        "moderation",
        "sora",
        "container",
    }

    # NOTE: We are explicitly excluding all "timestamped" models
    # because they are mostly just noise in the admin configuration panel
    # e.g. gpt-4o-2025-07-16, gpt-3.5-turbo-0613, etc.
    date_pattern = re.compile(r"-\d{4}")

    def is_valid_model(model: str) -> bool:
        model_lower = model.lower()
        return not any(
            ex in model_lower for ex in excluded_terms
        ) and not date_pattern.search(model)

    return sorted(
        (
            model
            for model in model_catalog.iter_models(LlmProviderNames.OPENAI, mode="chat")
            if is_valid_model(model)
        ),
        reverse=True,
    )


def get_anthropic_model_names() -> list[str]:
    """Get Anthropic model names from the vendored model catalog."""
    from onyx.llm import model_catalog

    return sorted(
        model_catalog.iter_models(LlmProviderNames.ANTHROPIC, mode="chat"), reverse=True
    )


def get_vertexai_model_names() -> list[str]:
    """Get Vertex AI model names from the vendored model catalog (the
    vertex_ai section already merges google-vertex and
    google-vertex-anthropic models)."""
    from onyx.llm import model_catalog

    vertex_models = set(
        model_catalog.iter_models(LlmProviderNames.VERTEX_AI, mode="chat")
    )

    return sorted(
        [
            model
            for model in vertex_models
            if "embed" not in model.lower()
            and "image" not in model.lower()
            and "video" not in model.lower()
            and "code" not in model.lower()
            and "veo" not in model.lower()  # video generation
            and "live" not in model.lower()  # live/streaming models
            and "tts" not in model.lower()  # text-to-speech
            and "native-audio" not in model.lower()  # audio models
            and "/" not in model  # filter out prefixed models like openai/gpt-oss
            and "search_api" not in model.lower()  # not a model
            and "-maas" not in model.lower()  # marketplace models
        ],
        reverse=True,
    )


def model_configurations_for_provider(
    provider_name: str, llm_recommendations: LLMRecommendations
) -> list[ModelConfigurationView]:
    recommended_visible_models = llm_recommendations.get_visible_models(provider_name)
    recommended_visible_models_names = [m.name for m in recommended_visible_models]
    display_name_by_name = {
        m.name: m.display_name for m in recommended_visible_models if m.display_name
    }
    default_model = llm_recommendations.get_default_model(provider_name)
    default_model_name = default_model.name if default_model else None

    # Preserve provider-defined ordering while de-duplicating.
    model_names: list[str] = []
    seen_model_names: set[str] = set()
    for model_name in (
        fetch_models_for_provider(provider_name) + recommended_visible_models_names
    ):
        if model_name in seen_model_names:
            continue
        seen_model_names.add(model_name)
        model_names.append(model_name)

    # Vertex model list can be large and mixed-vendor; alphabetical ordering
    # makes model discovery easier in admin selection UIs.
    if provider_name == VERTEXAI_PROVIDER_NAME:
        model_names = sorted(model_names, key=str.lower)

    return [
        ModelConfigurationView(
            name=model_name,
            is_visible=model_name in recommended_visible_models_names,
            is_recommended_default=model_name == default_model_name,
            max_input_tokens=get_max_input_tokens(model_name, provider_name),
            supports_image_input=model_supports_image_input(model_name, provider_name),
            # No provider row exists yet, so the surface is the provider default.
            supported_reasoning_efforts=supported_reasoning_efforts(
                provider_name,
                [model_name],
                resolve_api_surface(provider_name, None),
            ),
            display_name=display_name_by_name.get(model_name),
        )
        for model_name in model_names
    ]


def fetch_available_well_known_llms() -> list[WellKnownLLMProviderDescriptor]:
    llm_recommendations = get_recommendations()

    well_known_llms = []
    for provider_name in WELL_KNOWN_PROVIDER_NAMES:
        model_configurations = model_configurations_for_provider(
            provider_name, llm_recommendations
        )
        well_known_llms.append(
            WellKnownLLMProviderDescriptor(
                name=provider_name,
                known_models=model_configurations,
                recommended_default_model=llm_recommendations.get_default_model(
                    provider_name
                ),
            )
        )
    return well_known_llms


def fetch_models_for_provider(provider_name: str) -> list[str]:
    return _get_provider_to_models_map().get(provider_name, [])


def fetch_model_names_for_provider_as_set(provider_name: str) -> set[str] | None:
    model_names = fetch_models_for_provider(provider_name)
    return set(model_names) if model_names else None


def fetch_visible_model_names_for_provider_as_set(
    provider_name: str,
) -> set[str] | None:
    """Get visible model names for a provider.

    Note: Since we no longer maintain separate visible model lists,
    this returns all models (same as fetch_model_names_for_provider_as_set).
    Kept for backwards compatibility with alembic migrations.
    """
    return fetch_model_names_for_provider_as_set(provider_name)


def get_provider_display_name(provider_name: str) -> str:
    """Get human-friendly display name for an Onyx-supported provider.

    First checks Onyx-specific display names, then falls back to
    PROVIDER_DISPLAY_NAMES from constants.
    """
    # Display names for Onyx-supported LLM providers (used in admin UI provider selection).
    # These override PROVIDER_DISPLAY_NAMES for Onyx-specific branding.
    _ONYX_PROVIDER_DISPLAY_NAMES: dict[str, str] = {
        OPENAI_PROVIDER_NAME: "ChatGPT (OpenAI)",
        OLLAMA_PROVIDER_NAME: "Ollama",
        LM_STUDIO_PROVIDER_NAME: "LM Studio",
        ANTHROPIC_PROVIDER_NAME: "Claude (Anthropic)",
        AZURE_PROVIDER_NAME: "Azure OpenAI",
        BEDROCK_PROVIDER_NAME: "Amazon Bedrock",
        VERTEXAI_PROVIDER_NAME: "Google Vertex AI",
        OPENROUTER_PROVIDER_NAME: "OpenRouter",
        LITELLM_PROXY_PROVIDER_NAME: "LiteLLM Proxy",
        OPENAI_COMPATIBLE_PROVIDER_NAME: "OpenAI-Compatible",
        NEBIUS_TOKENFACTORY_PROVIDER_NAME: "Nebius TokenFactory",
        PORTKEY_PROVIDER_NAME: "Portkey",
        VERCEL_AI_GATEWAY_PROVIDER_NAME: "Vercel AI Gateway",
    }

    if provider_name in _ONYX_PROVIDER_DISPLAY_NAMES:
        return _ONYX_PROVIDER_DISPLAY_NAMES[provider_name]
    return PROVIDER_DISPLAY_NAMES.get(
        provider_name.lower(), provider_name.replace("_", " ").title()
    )


def fetch_default_model_for_provider(provider_name: str) -> str | None:
    """Fetch the default model for a provider.

    First checks the GitHub-hosted recommended-models.json config (via fetch_github_config),
    then falls back to hardcoded defaults if unavailable.
    """
    llm_recommendations = get_recommendations()
    default_model = llm_recommendations.get_default_model(provider_name)
    return default_model.name if default_model else None
