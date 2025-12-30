from enum import Enum

from pydantic import BaseModel

from onyx.llm.constants import LlmProviderNames
from onyx.llm.constants import PROVIDER_DISPLAY_NAMES
from onyx.llm.utils import model_supports_image_input
from onyx.server.manage.llm.models import ModelConfigurationView


class CustomConfigKeyType(Enum):
    # used for configuration values that require manual input
    # i.e., textual API keys (e.g., "abcd1234")
    TEXT_INPUT = "text_input"

    # used for configuration values that require a file to be selected/drag-and-dropped
    # i.e., file based credentials (e.g., "/path/to/credentials/file.json")
    FILE_INPUT = "file_input"

    # used for configuration values that require a selection from predefined options
    SELECT = "select"


class CustomConfigOption(BaseModel):
    label: str
    value: str
    description: str | None = None


class CustomConfigKey(BaseModel):
    name: str
    display_name: str
    description: str | None = None
    is_required: bool = True
    is_secret: bool = False
    key_type: CustomConfigKeyType = CustomConfigKeyType.TEXT_INPUT
    default_value: str | None = None
    options: list[CustomConfigOption] | None = None


class WellKnownLLMProviderDescriptor(BaseModel):
    name: str
    model_configurations: list[ModelConfigurationView]


# Curated list of OpenAI models to show by default in the UI
OPENAI_VISIBLE_MODEL_NAMES = {
    "gpt-5.2",
    "gpt-5-mini",
    "o1",
    "o3-mini",
    "gpt-4o",
    "gpt-4o-mini",
}


def _fallback_bedrock_regions() -> list[str]:
    # Fall back to a conservative set of well-known Bedrock regions if boto3 data isn't available.
    return [
        "us-east-1",
        "us-east-2",
        "us-gov-east-1",
        "us-gov-west-1",
        "us-west-2",
        "ap-northeast-1",
        "ap-south-1",
        "ap-southeast-1",
        "ap-southeast-2",
        "ap-east-1",
        "ca-central-1",
        "eu-central-1",
        "eu-west-2",
    ]


def _build_bedrock_region_options() -> list[CustomConfigOption]:
    try:
        import boto3

        session = boto3.session.Session()
        regions: set[str] = set()
        # Include both commercial and GovCloud partitions so GovCloud users can select their region.
        for partition_name in ("aws", "aws-us-gov"):
            try:
                regions.update(
                    session.get_available_regions(
                        "bedrock", partition_name=partition_name
                    )
                )
                regions.update(
                    session.get_available_regions(
                        "bedrock-runtime", partition_name=partition_name
                    )
                )
            except Exception:
                continue
        if not regions:
            raise ValueError("No Bedrock regions returned from boto3")
        sorted_regions = sorted(regions)
    except Exception:
        sorted_regions = _fallback_bedrock_regions()

    return [CustomConfigOption(label=region, value=region) for region in sorted_regions]


BEDROCK_REGION_OPTIONS = _build_bedrock_region_options()

OLLAMA_API_KEY_CONFIG_KEY = "OLLAMA_API_KEY"


# Models to exclude from Anthropic's model list (deprecated or duplicates)
_IGNORABLE_ANTHROPIC_MODELS = {
    "claude-2",
    "claude-instant-1",
    "anthropic/claude-3-5-sonnet-20241022",
}
# Curated list of Anthropic models to show by default in the UI
ANTHROPIC_VISIBLE_MODEL_NAMES = {
    "claude-opus-4-5",
    "claude-sonnet-4-5",
    "claude-haiku-4-5",
}


VERTEX_CREDENTIALS_FILE_KWARG = "vertex_credentials"
VERTEX_LOCATION_KWARG = "vertex_location"
# Curated list of Vertex AI models to show by default in the UI
VERTEXAI_VISIBLE_MODEL_NAMES = {
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.5-pro",
}


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


def _get_provider_to_models_map() -> dict[str, list[str]]:
    """Lazy-load provider model mappings to avoid importing litellm at module level.

    Dynamic providers (Bedrock, Ollama, OpenRouter) return empty lists here
    because their models are fetched directly from the source API, which is
    more up-to-date than LiteLLM's static lists.
    """
    return {
        LlmProviderNames.OPENAI: get_openai_model_names(),
        LlmProviderNames.BEDROCK: [],  # Dynamic - fetched from AWS API
        LlmProviderNames.ANTHROPIC: get_anthropic_model_names(),
        LlmProviderNames.VERTEX_AI: get_vertexai_model_names(),
        LlmProviderNames.OLLAMA_CHAT: [],  # Dynamic - fetched from Ollama API
        LlmProviderNames.OPENROUTER: [],  # Dynamic - fetched from OpenRouter API
    }


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


def fetch_available_well_known_llms() -> list[WellKnownLLMProviderDescriptor]:
    return [
        WellKnownLLMProviderDescriptor(
            name=LlmProviderNames.OPENAI,
            model_configurations=fetch_model_configurations_for_provider(
                LlmProviderNames.OPENAI
            ),
        ),
        WellKnownLLMProviderDescriptor(
            name=LlmProviderNames.OLLAMA_CHAT,
            model_configurations=fetch_model_configurations_for_provider(
                LlmProviderNames.OLLAMA_CHAT
            ),
        ),
        WellKnownLLMProviderDescriptor(
            name=LlmProviderNames.ANTHROPIC,
            model_configurations=fetch_model_configurations_for_provider(
                LlmProviderNames.ANTHROPIC
            ),
        ),
        WellKnownLLMProviderDescriptor(
            name=LlmProviderNames.AZURE,
            model_configurations=fetch_model_configurations_for_provider(
                LlmProviderNames.AZURE
            ),
        ),
        WellKnownLLMProviderDescriptor(
            name=LlmProviderNames.BEDROCK,
            model_configurations=fetch_model_configurations_for_provider(
                LlmProviderNames.BEDROCK
            ),
        ),
        WellKnownLLMProviderDescriptor(
            name=LlmProviderNames.VERTEX_AI,
            model_configurations=fetch_model_configurations_for_provider(
                LlmProviderNames.VERTEX_AI
            ),
        ),
        WellKnownLLMProviderDescriptor(
            name=LlmProviderNames.OPENROUTER,
            model_configurations=fetch_model_configurations_for_provider(
                LlmProviderNames.OPENROUTER
            ),
        ),
    ]


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


# Display names for Onyx-supported LLM providers (used in admin UI provider selection).
# These override PROVIDER_DISPLAY_NAMES for Onyx-specific branding.
_ONYX_PROVIDER_DISPLAY_NAMES: dict[str, str] = {
    LlmProviderNames.OPENAI: "ChatGPT (OpenAI)",
    LlmProviderNames.OLLAMA_CHAT: "Ollama",
    LlmProviderNames.ANTHROPIC: "Claude (Anthropic)",
    LlmProviderNames.AZURE: "Azure OpenAI",
    LlmProviderNames.BEDROCK: "Amazon Bedrock",
    LlmProviderNames.VERTEX_AI: "Google Vertex AI",
    LlmProviderNames.OPENROUTER: "OpenRouter",
}


def get_provider_display_name(provider_name: str) -> str:
    """Get human-friendly display name for an Onyx-supported provider.

    First checks Onyx-specific display names, then falls back to
    PROVIDER_DISPLAY_NAMES from constants.
    """
    if provider_name in _ONYX_PROVIDER_DISPLAY_NAMES:
        return _ONYX_PROVIDER_DISPLAY_NAMES[provider_name]
    return PROVIDER_DISPLAY_NAMES.get(
        provider_name.lower(), provider_name.replace("_", " ").title()
    )


def _get_visible_models_for_provider(provider_name: str) -> set[str]:
    """Get the set of models that should be visible by default for a provider."""
    _PROVIDER_TO_VISIBLE_MODELS: dict[str, set[str]] = {
        LlmProviderNames.OPENAI: OPENAI_VISIBLE_MODEL_NAMES,
        LlmProviderNames.ANTHROPIC: ANTHROPIC_VISIBLE_MODEL_NAMES,
        LlmProviderNames.VERTEX_AI: VERTEXAI_VISIBLE_MODEL_NAMES,
    }
    return _PROVIDER_TO_VISIBLE_MODELS.get(provider_name, set())


def fetch_model_configurations_for_provider(
    provider_name: str,
) -> list[ModelConfigurationView]:
    """Fetch model configurations for a static provider (OpenAI, Anthropic, Vertex AI).

    Looks up max_input_tokens from LiteLLM's model_cost. If not found, stores None
    and the runtime will use the fallback (32000).

    Models in the curated visible lists (OPENAI_VISIBLE_MODEL_NAMES, etc.) are
    marked as is_visible=True by default.
    """
    from onyx.llm.utils import get_max_input_tokens

    visible_models = _get_visible_models_for_provider(provider_name)
    configs = []
    for model_name in fetch_models_for_provider(provider_name):
        max_input_tokens = get_max_input_tokens(
            model_name=model_name,
            model_provider=provider_name,
        )

        configs.append(
            ModelConfigurationView(
                name=model_name,
                is_visible=model_name in visible_models,
                max_input_tokens=max_input_tokens,
                supports_image_input=model_supports_image_input(
                    model_name=model_name,
                    model_provider=provider_name,
                ),
            )
        )
    return configs
