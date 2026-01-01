import json
import pathlib

from onyx.llm.constants import LlmProviderNames
from onyx.llm.constants import PROVIDER_DISPLAY_NAMES
from onyx.llm.constants import WELL_KNOWN_PROVIDER_NAMES
from onyx.llm.utils import get_max_input_tokens
from onyx.llm.utils import model_supports_image_input
from onyx.llm.well_known_providers.auto_update_models import LLMRecommendations
from onyx.llm.well_known_providers.auto_update_service import (
    fetch_llm_recommendations_from_github,
)
from onyx.llm.well_known_providers.constants import ANTHROPIC_PROVIDER_NAME
from onyx.llm.well_known_providers.constants import AZURE_PROVIDER_NAME
from onyx.llm.well_known_providers.constants import BEDROCK_PROVIDER_NAME
from onyx.llm.well_known_providers.constants import OLLAMA_PROVIDER_NAME
from onyx.llm.well_known_providers.constants import OPENAI_PROVIDER_NAME
from onyx.llm.well_known_providers.constants import OPENROUTER_PROVIDER_NAME
from onyx.llm.well_known_providers.constants import VERTEXAI_PROVIDER_NAME
from onyx.llm.well_known_providers.models import WellKnownLLMProviderDescriptor
from onyx.server.manage.llm.models import ModelConfigurationView
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _get_provider_to_models_map() -> dict[str, list[str]]:
    """Lazy-load provider model mappings to avoid importing litellm at module level.

    Dynamic providers (Bedrock, Ollama, OpenRouter) return empty lists here
    because their models are fetched directly from the source API, which is
    more up-to-date than LiteLLM's static lists.
    """
    return {
        OPENAI_PROVIDER_NAME: get_openai_model_names(),
        BEDROCK_PROVIDER_NAME: [],  # Dynamic - fetched from AWS API
        ANTHROPIC_PROVIDER_NAME: get_anthropic_model_names(),
        VERTEXAI_PROVIDER_NAME: get_vertexai_model_names(),
        OLLAMA_PROVIDER_NAME: [],  # Dynamic - fetched from Ollama API
        OPENROUTER_PROVIDER_NAME: [],  # Dynamic - fetched from OpenRouter API
    }


def get_recommendations() -> LLMRecommendations:
    """Get the recommendations from the GitHub config."""
    recommendations_from_github = fetch_llm_recommendations_from_github()
    if recommendations_from_github:
        return recommendations_from_github

    # Fall back to json bundled with code
    json_path = pathlib.Path(__file__).parent / "recommended-models.json"
    with open(json_path, "r") as f:
        json_config = json.load(f)

    recommendations_from_json = LLMRecommendations.model_validate(json_config)
    return recommendations_from_json


def is_obsolete_model(model_name: str, provider: str) -> bool:
    """Check if a model is obsolete and should be filtered out.

    Filters models that are 2+ major versions behind or deprecated.
    This is the single source of truth for obsolete model detection.
    """
    model_lower = model_name.lower()

    # OpenAI obsolete models
    if provider == LlmProviderNames.OPENAI:
        # GPT-3 models are obsolete
        if "gpt-3" in model_lower:
            return True
        # Legacy models
        deprecated = {
            "text-davinci-003",
            "text-davinci-002",
            "text-curie-001",
            "text-babbage-001",
            "text-ada-001",
            "davinci",
            "curie",
            "babbage",
            "ada",
        }
        if model_lower in deprecated:
            return True

    # Anthropic obsolete models
    if provider == LlmProviderNames.ANTHROPIC:
        if "claude-2" in model_lower or "claude-instant" in model_lower:
            return True

    # Vertex AI obsolete models
    if provider == LlmProviderNames.VERTEX_AI:
        if "gemini-1.0" in model_lower:
            return True
        if "palm" in model_lower or "bison" in model_lower:
            return True

    return False


def get_openai_model_names() -> list[str]:
    """Get OpenAI model names dynamically from litellm."""
    import re
    import litellm

    # TODO: remove these lists once we have a comprehensive model configuration page
    # The ideal flow should be: fetch all available models --> filter by type
    # --> allow user to modify filters and select models based on current context
    non_chat_model_terms = {
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
    deprecated_model_terms = {"babbage", "davinci", "gpt-3.5", "gpt-4-"}
    excluded_terms = non_chat_model_terms | deprecated_model_terms

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
            model.removeprefix("openai/")
            for model in litellm.open_ai_chat_completion_models
            if is_valid_model(model)
        ),
        reverse=True,
    )


def get_anthropic_model_names() -> list[str]:
    """Get Anthropic model names dynamically from litellm."""
    import litellm

    # Models to exclude from Anthropic's model list (deprecated or duplicates)
    _IGNORABLE_ANTHROPIC_MODELS = {
        "claude-2",
        "claude-instant-1",
        "anthropic/claude-3-5-sonnet-20241022",
    }

    return sorted(
        [
            model
            for model in litellm.anthropic_models
            if model not in _IGNORABLE_ANTHROPIC_MODELS
            and not is_obsolete_model(model, LlmProviderNames.ANTHROPIC)
        ],
        reverse=True,
    )


def get_vertexai_model_names() -> list[str]:
    """Get Vertex AI model names dynamically from litellm model_cost."""
    import litellm

    # Combine all vertex model sets
    vertex_models: set[str] = set()
    vertex_model_sets = [
        "vertex_chat_models",
        "vertex_language_models",
        "vertex_anthropic_models",
        "vertex_llama3_models",
        "vertex_mistral_models",
        "vertex_ai_ai21_models",
        "vertex_deepseek_models",
    ]
    for attr in vertex_model_sets:
        if hasattr(litellm, attr):
            vertex_models.update(getattr(litellm, attr))

    # Also extract from model_cost for any models not in the sets
    for key in litellm.model_cost.keys():
        if key.startswith("vertex_ai/"):
            model_name = key.replace("vertex_ai/", "")
            vertex_models.add(model_name)

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
            and not is_obsolete_model(model, LlmProviderNames.VERTEX_AI)
        ],
        reverse=True,
    )


def model_configurations_for_provider(
    provider_name: str, llm_recommendations: LLMRecommendations
) -> list[ModelConfigurationView]:
    recommended_visible_models = llm_recommendations.get_visible_models(provider_name)
    recommended_visible_models_names = [m.name for m in recommended_visible_models]
    return [
        ModelConfigurationView(
            name=model_name,
            is_visible=model_name in recommended_visible_models_names,
            max_input_tokens=get_max_input_tokens(model_name, provider_name),
            supports_image_input=model_supports_image_input(model_name, provider_name),
        )
        for model_name in set(fetch_models_for_provider(provider_name))
        | set(recommended_visible_models_names)
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
        ANTHROPIC_PROVIDER_NAME: "Claude (Anthropic)",
        AZURE_PROVIDER_NAME: "Azure OpenAI",
        BEDROCK_PROVIDER_NAME: "Amazon Bedrock",
        VERTEXAI_PROVIDER_NAME: "Google Vertex AI",
        OPENROUTER_PROVIDER_NAME: "OpenRouter",
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
