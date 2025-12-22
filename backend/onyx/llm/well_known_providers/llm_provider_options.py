import json
import pathlib

from onyx.llm.constants import PROVIDER_DISPLAY_NAMES
from onyx.llm.utils import model_supports_image_input
from onyx.llm.well_known_providers.auto_update_models import LLMRecommendations
from onyx.llm.well_known_providers.constants import ANTHROPIC_PROVIDER_NAME
from onyx.llm.well_known_providers.constants import AZURE_PROVIDER_NAME
from onyx.llm.well_known_providers.constants import BEDROCK_PROVIDER_NAME
from onyx.llm.well_known_providers.constants import BEDROCK_REGION_OPTIONS
from onyx.llm.well_known_providers.constants import OLLAMA_API_KEY_CONFIG_KEY
from onyx.llm.well_known_providers.constants import OLLAMA_PROVIDER_NAME
from onyx.llm.well_known_providers.constants import OPENAI_PROVIDER_NAME
from onyx.llm.well_known_providers.constants import OPENROUTER_PROVIDER_NAME
from onyx.llm.well_known_providers.constants import VERTEX_CREDENTIALS_FILE_KWARG
from onyx.llm.well_known_providers.constants import VERTEX_LOCATION_KWARG
from onyx.llm.well_known_providers.constants import VERTEXAI_PROVIDER_NAME
from onyx.llm.well_known_providers.models import CustomConfigKey
from onyx.llm.well_known_providers.models import CustomConfigKeyType
from onyx.llm.well_known_providers.models import CustomConfigOption
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


def _get_reccomendations() -> LLMRecommendations:
    """Get the recommendations from the GitHub config."""
    # recommendations_from_github = fetch_llm_recommendations_from_github()
    # if recommendations_from_github:
    #     return recommendations_from_github

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
    if provider == "openai":
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
    if provider == "anthropic":
        if "claude-2" in model_lower or "claude-instant" in model_lower:
            return True

    # Vertex AI obsolete models
    if provider == "vertex_ai":
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
            and not is_obsolete_model(model, ANTHROPIC_PROVIDER_NAME)
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
            and not is_obsolete_model(model, VERTEXAI_PROVIDER_NAME)
        ],
        reverse=True,
    )


def fetch_available_well_known_llms() -> list[WellKnownLLMProviderDescriptor]:
    return [
        WellKnownLLMProviderDescriptor(
            name=OPENAI_PROVIDER_NAME,
            display_name="OpenAI",
            title="GPT",
            api_key_required=True,
            api_base_required=False,
            api_version_required=False,
            custom_config_keys=[],
            model_configurations=fetch_model_configurations_for_provider(
                OPENAI_PROVIDER_NAME
            ),
            default_model=fetch_default_model_for_provider(OPENAI_PROVIDER_NAME),
        ),
        WellKnownLLMProviderDescriptor(
            name=OLLAMA_PROVIDER_NAME,
            display_name="Ollama",
            title="Ollama",
            api_key_required=False,
            api_base_required=True,
            api_version_required=False,
            custom_config_keys=[
                CustomConfigKey(
                    name=OLLAMA_API_KEY_CONFIG_KEY,
                    display_name="Ollama API Key",
                    description="Optional API key used when connecting to Ollama Cloud (i.e. API base is https://ollama.com).",
                    is_required=False,
                    is_secret=True,
                )
            ],
            model_configurations=fetch_model_configurations_for_provider(
                OLLAMA_PROVIDER_NAME
            ),
            # we don't know what models are available, so we can't pre-fetch a default
            default_model=None,
            default_api_base="http://127.0.0.1:11434",
        ),
        WellKnownLLMProviderDescriptor(
            name=ANTHROPIC_PROVIDER_NAME,
            display_name="Anthropic",
            title="Claude",
            api_key_required=True,
            api_base_required=False,
            api_version_required=False,
            custom_config_keys=[],
            model_configurations=fetch_model_configurations_for_provider(
                ANTHROPIC_PROVIDER_NAME
            ),
            default_model=fetch_default_model_for_provider(ANTHROPIC_PROVIDER_NAME),
        ),
        WellKnownLLMProviderDescriptor(
            name=AZURE_PROVIDER_NAME,
            display_name="Microsoft Azure Cloud",
            title="Azure OpenAI",
            api_key_required=True,
            api_base_required=True,
            api_version_required=True,
            custom_config_keys=[],
            model_configurations=fetch_model_configurations_for_provider(
                AZURE_PROVIDER_NAME
            ),
            deployment_name_required=True,
            single_model_supported=True,
        ),
        WellKnownLLMProviderDescriptor(
            name=BEDROCK_PROVIDER_NAME,
            display_name="AWS",
            title="Amazon Bedrock",
            api_key_required=False,
            api_base_required=False,
            api_version_required=False,
            custom_config_keys=[
                CustomConfigKey(
                    name="AWS_REGION_NAME",
                    display_name="AWS Region Name",
                    description="Region where your Amazon Bedrock models are hosted.",
                    key_type=CustomConfigKeyType.SELECT,
                    options=BEDROCK_REGION_OPTIONS,
                ),
                CustomConfigKey(
                    name="BEDROCK_AUTH_METHOD",
                    display_name="Authentication",
                    description="Choose how Onyx should authenticate with Bedrock.",
                    is_required=False,
                    key_type=CustomConfigKeyType.SELECT,
                    default_value="access_key",
                    options=[
                        CustomConfigOption(
                            label="Environment IAM Role",
                            value="iam",
                            description="Recommended for AWS environments",
                        ),
                        CustomConfigOption(
                            label="Access Key",
                            value="access_key",
                            description="For non-AWS environments",
                        ),
                        CustomConfigOption(
                            label="Long-term API Key",
                            value="long_term_api_key",
                            description="For non-AWS environments",
                        ),
                    ],
                ),
                CustomConfigKey(
                    name="AWS_ACCESS_KEY_ID",
                    display_name="AWS Access Key ID",
                    is_required=False,
                    description="If using IAM role or a long-term API key, leave this field blank.",
                ),
                CustomConfigKey(
                    name="AWS_SECRET_ACCESS_KEY",
                    display_name="AWS Secret Access Key",
                    is_required=False,
                    is_secret=True,
                    description="If using IAM role or a long-term API key, leave this field blank.",
                ),
                CustomConfigKey(
                    name="AWS_BEARER_TOKEN_BEDROCK",
                    display_name="AWS Bedrock Long-term API Key",
                    is_required=False,
                    is_secret=True,
                    description=(
                        "If using IAM role or access key, leave this field blank."
                    ),
                ),
            ],
            model_configurations=fetch_model_configurations_for_provider(
                BEDROCK_PROVIDER_NAME
            ),
            # we don't know what models are available, so we can't pre-fetch a default
            default_model=None,
        ),
        WellKnownLLMProviderDescriptor(
            name=VERTEXAI_PROVIDER_NAME,
            display_name="Google Cloud Vertex AI",
            title="Gemini",
            api_key_required=False,
            api_base_required=False,
            api_version_required=False,
            model_configurations=fetch_model_configurations_for_provider(
                VERTEXAI_PROVIDER_NAME
            ),
            custom_config_keys=[
                CustomConfigKey(
                    name=VERTEX_CREDENTIALS_FILE_KWARG,
                    display_name="Credentials File",
                    description="This should be a JSON file containing some private credentials.",
                    is_required=True,
                    is_secret=False,
                    key_type=CustomConfigKeyType.FILE_INPUT,
                ),
                CustomConfigKey(
                    name=VERTEX_LOCATION_KWARG,
                    display_name="Location",
                    description="The location of the Vertex AI model. Please refer to the "
                    "[Vertex AI configuration docs](https://docs.onyx.app/admins/ai_models/google_ai) for all possible values.",
                    is_required=False,
                    is_secret=False,
                    key_type=CustomConfigKeyType.TEXT_INPUT,
                    default_value="us-east1",
                ),
            ],
            default_model=fetch_default_model_for_provider(VERTEXAI_PROVIDER_NAME),
        ),
        WellKnownLLMProviderDescriptor(
            name=OPENROUTER_PROVIDER_NAME,
            display_name="OpenRouter",
            title="OpenRouter",
            api_key_required=True,
            api_base_required=True,
            api_version_required=False,
            custom_config_keys=[],
            model_configurations=fetch_model_configurations_for_provider(
                OPENROUTER_PROVIDER_NAME
            ),
            default_model=fetch_default_model_for_provider(OPENROUTER_PROVIDER_NAME),
            default_api_base="https://openrouter.ai/api/v1",
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

    llm_recommendations = _get_reccomendations()
    recommended_visible_models = llm_recommendations.get_visible_models(provider_name)
    recommended_visible_model_names = {
        model.name for model in recommended_visible_models
    }
    configs = []

    model_names = set(fetch_models_for_provider(provider_name)).union(
        recommended_visible_model_names
    )
    for model_name in model_names:
        max_input_tokens = get_max_input_tokens(
            model_name=model_name,
            model_provider=provider_name,
        )

        configs.append(
            ModelConfigurationView(
                name=model_name,
                is_visible=model_name in recommended_visible_model_names,
                max_input_tokens=max_input_tokens,
                supports_image_input=model_supports_image_input(
                    model_name=model_name,
                    model_provider=provider_name,
                ),
            )
        )
    return configs


def fetch_default_model_for_provider(provider_name: str) -> str | None:
    """Fetch the default model for a provider.

    First checks the GitHub-hosted recommended-models.json config (via fetch_github_config),
    then falls back to hardcoded defaults if unavailable.
    """
    llm_recommendations = _get_reccomendations()
    default_model = llm_recommendations.get_default_model(provider_name)
    return default_model.name if default_model else None
