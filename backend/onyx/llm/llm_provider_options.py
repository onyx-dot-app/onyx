from enum import Enum
from typing import TypedDict

from pydantic import BaseModel

from onyx.llm.chat_llm import VERTEX_CREDENTIALS_FILE_KWARG
from onyx.llm.chat_llm import VERTEX_LOCATION_KWARG
from onyx.llm.utils import model_supports_image_input
from onyx.server.manage.llm.models import ModelConfigurationView


class CuratedModelDict(TypedDict):
    name: str
    friendly_name: str
    recommended_default_model: bool
    recommended_fast_default_model: bool
    recommended_is_visible: bool
    deprecated: bool


class CustomConfigKeyType(Enum):
    # used for configuration values that require manual input
    # i.e., textual API keys (e.g., "abcd1234")
    TEXT_INPUT = "text_input"

    # used for configuration values that require a file to be selected/drag-and-dropped
    # i.e., file based credentials (e.g., "/path/to/credentials/file.json")
    FILE_INPUT = "file_input"


class CustomConfigKey(BaseModel):
    name: str
    display_name: str
    description: str | None = None
    is_required: bool = True
    is_secret: bool = False
    key_type: CustomConfigKeyType = CustomConfigKeyType.TEXT_INPUT
    default_value: str | None = None


class WellKnownLLMProviderDescriptor(BaseModel):
    name: str
    display_name: str
    api_key_required: bool
    api_base_required: bool
    api_version_required: bool
    custom_config_keys: list[CustomConfigKey] | None = None
    model_configurations: list[ModelConfigurationView]
    default_model: str | None = None
    default_fast_model: str | None = None
    # set for providers like Azure, which require a deployment name.
    deployment_name_required: bool = False
    # set for providers like Azure, which support a single model per deployment.
    single_model_supported: bool = False
    # indicates whether this provider has curated models available
    has_curated_models: bool = False


# TODO Before shipping:
# Backfill existing litellm models (with deprecated: True if we wish to hide) for backwards compatibility
curated_models: dict[str, list[CuratedModelDict]] = {
    "openai": [
        {
            "name": "o1",
            "friendly_name": "OpenAI o1",
            "recommended_default_model": False,
            "recommended_fast_default_model": False,
            "recommended_is_visible": False,
            "deprecated": False,
        },
        {
            "name": "o3-mini",
            "friendly_name": "OpenAI o3 Mini",
            "recommended_default_model": True,
            "recommended_fast_default_model": False,
            "recommended_is_visible": True,
            "deprecated": False,
        },
        {
            "name": "gpt-4o",
            "friendly_name": "GPT 4o",
            "recommended_default_model": False,
            "recommended_fast_default_model": False,
            "recommended_is_visible": False,
            "deprecated": False,
        },
        {
            "name": "gpt-4o-mini",
            "friendly_name": "GPT 4o Mini",
            "recommended_default_model": False,
            "recommended_fast_default_model": True,
            "recommended_is_visible": True,
            "deprecated": False,
        },
        {
            "name": "o3",
            "friendly_name": "OpenAI o3",
            "recommended_default_model": False,
            "recommended_fast_default_model": False,
            "recommended_is_visible": False,
            "deprecated": False,
        },
        {
            "name": "o4-mini",
            "friendly_name": "OpenAI o4 Mini",
            "recommended_default_model": False,
            "recommended_fast_default_model": False,
            "recommended_is_visible": False,
            "deprecated": False,
        },
        {
            "name": "o1-mini",
            "friendly_name": "OpenAI o1 Mini",
            "recommended_default_model": False,
            "recommended_fast_default_model": False,
            "recommended_is_visible": False,
            "deprecated": False,
        },
        {
            "name": "gpt-4.1",
            "friendly_name": "GPT 4.1",
            "recommended_default_model": False,
            "recommended_fast_default_model": False,
            "recommended_is_visible": False,
            "deprecated": False,
        },
        {
            "name": "gpt-4",
            "friendly_name": "GPT 4",
            "recommended_default_model": False,
            "recommended_fast_default_model": False,
            "recommended_is_visible": False,
            "deprecated": False,
        },
        {
            "name": "gpt-4-turbo",
            "friendly_name": "GPT 4 Turbo",
            "recommended_default_model": False,
            "recommended_fast_default_model": False,
            "recommended_is_visible": False,
            "deprecated": False,
        },
    ],
    "anthropic": [
        {
            "name": "claude-4-sonnet-20250514",
            "friendly_name": "Claude 4 Sonnet",
            "recommended_default_model": True,
            "recommended_fast_default_model": False,
            "recommended_is_visible": True,
            "deprecated": False,
        },
        {
            "name": "claude-3-7-sonnet-20250219",
            "friendly_name": "Claude 3.7 Sonnet (February 2025)",
            "recommended_default_model": False,
            "recommended_fast_default_model": False,
            "recommended_is_visible": False,
            "deprecated": False,
        },
        {
            "name": "claude-3-5-sonnet-20241022",
            "friendly_name": "Claude 3.5 Sonnet (October 2024)",
            "recommended_default_model": False,
            "recommended_fast_default_model": True,
            "recommended_is_visible": True,
            "deprecated": False,
        },
        {
            "name": "claude-3-opus-20240229",
            "friendly_name": "Claude 3 Opus",
            "recommended_default_model": False,
            "recommended_fast_default_model": False,
            "recommended_is_visible": False,
            "deprecated": True,
        },
        {
            "name": "claude-3-sonnet-20240229",
            "friendly_name": "Claude 3 Sonnet",
            "recommended_default_model": False,
            "recommended_fast_default_model": False,
            "recommended_is_visible": False,
            "deprecated": False,
        },
        {
            "name": "claude-3-haiku-20240307",
            "friendly_name": "Claude 3 Haiku",
            "recommended_default_model": False,
            "recommended_fast_default_model": False,
            "recommended_is_visible": False,
            "deprecated": True,
        },
    ],
    "vertex_ai": [
        {
            "name": "gemini-2.0-flash",
            "friendly_name": "Gemini 2.0 Flash",
            "recommended_default_model": True,
            "recommended_fast_default_model": False,
            "recommended_is_visible": True,
            "deprecated": False,
        },
        {
            "name": "gemini-2.0-flash-lite",
            "friendly_name": "Gemini 2.0 Flash Lite",
            "recommended_default_model": False,
            "recommended_fast_default_model": True,
            "recommended_is_visible": True,
            "deprecated": False,
        },
        {
            "name": "gemini-2.5-pro-preview-06-05",
            "friendly_name": "Gemini 2.5 Pro Preview (June 2024)",
            "recommended_default_model": False,
            "recommended_fast_default_model": False,
            "recommended_is_visible": False,
            "deprecated": False,
        },
        {
            "name": "gemini-2.5-pro-preview-05-06",
            "friendly_name": "Gemini 2.5 Pro Preview (May 2024)",
            "recommended_default_model": False,
            "recommended_fast_default_model": False,
            "recommended_is_visible": False,
            "deprecated": False,
        },
        {
            "name": "gemini-2.0-flash-lite-001",
            "friendly_name": "Gemini 2.0 Flash Lite (Version 001)",
            "recommended_default_model": False,
            "recommended_fast_default_model": False,
            "recommended_is_visible": False,
            "deprecated": False,
        },
        {
            "name": "gemini-2.0-flash-001",
            "friendly_name": "Gemini 2.0 Flash (Version 001)",
            "recommended_default_model": False,
            "recommended_fast_default_model": False,
            "recommended_is_visible": False,
            "deprecated": False,
        },
        {
            "name": "gemini-2.0-flash-exp",
            "friendly_name": "Gemini 2.0 Flash Experimental",
            "recommended_default_model": False,
            "recommended_fast_default_model": False,
            "recommended_is_visible": False,
            "deprecated": False,
        },
        {
            "name": "gemini-1.5-pro",
            "friendly_name": "Gemini 1.5 Pro",
            "recommended_default_model": False,
            "recommended_fast_default_model": False,
            "recommended_is_visible": False,
            "deprecated": False,
        },
        {
            "name": "gemini-1.5-pro-001",
            "friendly_name": "Gemini 1.5 Pro (Version 001)",
            "recommended_default_model": False,
            "recommended_fast_default_model": False,
            "recommended_is_visible": False,
            "deprecated": False,
        },
        {
            "name": "gemini-1.5-pro-002",
            "friendly_name": "Gemini 1.5 Pro (Version 002)",
            "recommended_default_model": False,
            "recommended_fast_default_model": False,
            "recommended_is_visible": False,
            "deprecated": False,
        },
        {
            "name": "gemini-1.5-flash",
            "friendly_name": "Gemini 1.5 Flash",
            "recommended_default_model": False,
            "recommended_fast_default_model": False,
            "recommended_is_visible": False,
            "deprecated": False,
        },
        {
            "name": "gemini-1.5-flash-001",
            "friendly_name": "Gemini 1.5 Flash (Version 001)",
            "recommended_default_model": False,
            "recommended_fast_default_model": False,
            "recommended_is_visible": False,
            "deprecated": False,
        },
        {
            "name": "gemini-1.5-flash-002",
            "friendly_name": "Gemini 1.5 Flash (Version 002)",
            "recommended_default_model": False,
            "recommended_fast_default_model": False,
            "recommended_is_visible": False,
            "deprecated": False,
        },
        {
            "name": "claude-sonnet-4",
            "friendly_name": "Claude Sonnet 4 (Vertex AI)",
            "recommended_default_model": False,
            "recommended_fast_default_model": False,
            "recommended_is_visible": False,
            "deprecated": False,
        },
        {
            "name": "claude-opus-4",
            "friendly_name": "Claude Opus 4 (Vertex AI)",
            "recommended_default_model": False,
            "recommended_fast_default_model": False,
            "recommended_is_visible": False,
            "deprecated": False,
        },
        {
            "name": "claude-3-7-sonnet@20250219",
            "friendly_name": "Claude 3.7 Sonnet (Vertex AI)",
            "recommended_default_model": False,
            "recommended_fast_default_model": False,
            "recommended_is_visible": False,
            "deprecated": False,
        },
    ],
    "bedrock": [
        {
            "name": "anthropic.claude-3-7-sonnet-20250219-v1:0",
            "friendly_name": "Claude 3.7 Sonnet (Bedrock)",
            "recommended_default_model": True,
            "recommended_fast_default_model": False,
            "recommended_is_visible": True,
            "deprecated": False,
        },
        {
            "name": "anthropic.claude-3-5-sonnet-20241022-v2:0",
            "friendly_name": "Claude 3.5 Sonnet (Bedrock)",
            "recommended_default_model": False,
            "recommended_fast_default_model": True,
            "recommended_is_visible": True,
            "deprecated": False,
        },
        {
            "name": "anthropic.claude-3-opus-20240229-v1:0",
            "friendly_name": "Claude 3 Opus (Bedrock)",
            "recommended_default_model": False,
            "recommended_fast_default_model": False,
            "recommended_is_visible": False,
            "deprecated": False,
        },
        {
            "name": "anthropic.claude-3-sonnet-20240229-v1:0",
            "friendly_name": "Claude 3 Sonnet (Bedrock)",
            "recommended_default_model": False,
            "recommended_fast_default_model": False,
            "recommended_is_visible": False,
            "deprecated": False,
        },
        {
            "name": "anthropic.claude-3-haiku-20240307-v1:0",
            "friendly_name": "Claude 3 Haiku (Bedrock)",
            "recommended_default_model": False,
            "recommended_fast_default_model": False,
            "recommended_is_visible": False,
            "deprecated": False,
        },
        {
            "name": "meta.llama3-1-70b-instruct-v1:0",
            "friendly_name": "Llama 3.1 70B Instruct",
            "recommended_default_model": False,
            "recommended_fast_default_model": False,
            "recommended_is_visible": False,
            "deprecated": False,
        },
        {
            "name": "meta.llama3-1-8b-instruct-v1:0",
            "friendly_name": "Llama 3.1 8B Instruct",
            "recommended_default_model": False,
            "recommended_fast_default_model": False,
            "recommended_is_visible": False,
            "deprecated": False,
        },
        {
            "name": "meta.llama3-2-90b-instruct-v1:0",
            "friendly_name": "Llama 3.2 90B Instruct",
            "recommended_default_model": False,
            "recommended_fast_default_model": False,
            "recommended_is_visible": False,
            "deprecated": False,
        },
        {
            "name": "meta.llama3-2-11b-instruct-v1:0",
            "friendly_name": "Llama 3.2 11B Instruct",
            "recommended_default_model": False,
            "recommended_fast_default_model": False,
            "recommended_is_visible": False,
            "deprecated": False,
        },
        {
            "name": "meta.llama3-3-70b-instruct-v1:0",
            "friendly_name": "Llama 3.3 70B Instruct",
            "recommended_default_model": False,
            "recommended_fast_default_model": False,
            "recommended_is_visible": False,
            "deprecated": False,
        },
        {
            "name": "amazon.nova-micro-v1:0",
            "friendly_name": "Amazon Nova Micro",
            "recommended_default_model": False,
            "recommended_fast_default_model": False,
            "recommended_is_visible": False,
            "deprecated": False,
        },
        {
            "name": "amazon.nova-lite-v1:0",
            "friendly_name": "Amazon Nova Lite",
            "recommended_default_model": False,
            "recommended_fast_default_model": False,
            "recommended_is_visible": False,
            "deprecated": False,
        },
        {
            "name": "amazon.nova-pro-v1:0",
            "friendly_name": "Amazon Nova Pro",
            "recommended_default_model": False,
            "recommended_fast_default_model": False,
            "recommended_is_visible": False,
            "deprecated": False,
        },
        {
            "name": "mistral.mistral-large-2402-v1:0",
            "friendly_name": "Mistral Large (February 2024)",
            "recommended_default_model": False,
            "recommended_fast_default_model": False,
            "recommended_is_visible": False,
            "deprecated": False,
        },
        {
            "name": "mistral.mistral-large-2407-v1:0",
            "friendly_name": "Mistral Large (July 2024)",
            "recommended_default_model": False,
            "recommended_fast_default_model": False,
            "recommended_is_visible": False,
            "deprecated": False,
        },
        {
            "name": "mistral.mistral-small-2402-v1:0",
            "friendly_name": "Mistral Small (February 2024)",
            "recommended_default_model": False,
            "recommended_fast_default_model": False,
            "recommended_is_visible": False,
            "deprecated": False,
        },
        {
            "name": "ai21.jamba-instruct-v1:0",
            "friendly_name": "AI21 Jamba Instruct",
            "recommended_default_model": False,
            "recommended_fast_default_model": False,
            "recommended_is_visible": False,
            "deprecated": False,
        },
        {
            "name": "cohere.command-r-plus-v1:0",
            "friendly_name": "Cohere Command R+",
            "recommended_default_model": False,
            "recommended_fast_default_model": False,
            "recommended_is_visible": False,
            "deprecated": False,
        },
        {
            "name": "cohere.command-r-v1:0",
            "friendly_name": "Cohere Command R",
            "recommended_default_model": False,
            "recommended_fast_default_model": False,
            "recommended_is_visible": False,
            "deprecated": False,
        },
    ],
}


def get_curated_model_names(provider_name: str) -> list[str]:
    """Get list of model names from curated_models for a specific provider."""
    if provider_name not in curated_models:
        return []
    return [
        model["name"]
        for model in curated_models[provider_name]
        if not model.get("deprecated", False)
    ]


def get_curated_model_info(
    provider_name: str, model_name: str
) -> CuratedModelDict | None:
    """Get curated model information for a specific provider and model."""
    if provider_name not in curated_models:
        return None

    for model in curated_models[provider_name]:
        if model["name"] == model_name:
            return model

    return None


def get_curated_is_visible(provider_name: str, model_name: str) -> bool:
    """Get the recommended_is_visible value from curated_models for a specific model."""
    model_info = get_curated_model_info(provider_name, model_name)
    if model_info:
        return model_info["recommended_is_visible"]
    return False


def get_curated_recommended_default_model(provider_name: str) -> str | None:
    """Get the recommended default model from curated_models for a specific provider."""
    if provider_name not in curated_models:
        return None

    for model in curated_models[provider_name]:
        if model.get("recommended_default_model", False) and not model.get(
            "deprecated", False
        ):
            return model["name"]

    return None


def get_curated_recommended_fast_default_model(provider_name: str) -> str | None:
    """Get the recommended fast default model from curated_models for a specific provider."""
    if provider_name not in curated_models:
        return None

    for model in curated_models[provider_name]:
        if model.get("recommended_fast_default_model", False) and not model.get(
            "deprecated", False
        ):
            return model["name"]

    return None


# TODO Before shipping: These values are taken from curated_models.
# Ensure the values before and after this commit are the exact same.
# Do that for basically the rest of this file.
OPENAI_PROVIDER_NAME = "openai"
OPEN_AI_MODEL_NAMES = get_curated_model_names("openai")
OPEN_AI_VISIBLE_MODEL_NAMES = [
    model["name"]
    for model in curated_models.get("openai", [])
    if model.get("recommended_is_visible", False) and not model.get("deprecated", False)
]

BEDROCK_PROVIDER_NAME = "bedrock"
BEDROCK_MODEL_NAMES = get_curated_model_names("bedrock")
BEDROCK_DEFAULT_MODEL = (
    get_curated_recommended_default_model("bedrock")
    or "anthropic.claude-3-5-sonnet-20241022-v2:0"
)

ANTHROPIC_PROVIDER_NAME = "anthropic"
ANTHROPIC_MODEL_NAMES = get_curated_model_names("anthropic")
ANTHROPIC_VISIBLE_MODEL_NAMES = [
    model["name"]
    for model in curated_models.get("anthropic", [])
    if model.get("recommended_is_visible", False) and not model.get("deprecated", False)
]

AZURE_PROVIDER_NAME = "azure"


VERTEXAI_PROVIDER_NAME = "vertex_ai"
VERTEXAI_DEFAULT_MODEL = (
    get_curated_recommended_default_model("vertex_ai") or "gemini-2.0-flash"
)
VERTEXAI_DEFAULT_FAST_MODEL = (
    get_curated_recommended_fast_default_model("vertex_ai") or "gemini-2.0-flash-lite"
)
VERTEXAI_MODEL_NAMES = get_curated_model_names("vertex_ai")
VERTEXAI_VISIBLE_MODEL_NAMES = [
    model["name"]
    for model in curated_models.get("vertex_ai", [])
    if model.get("recommended_is_visible", False) and not model.get("deprecated", False)
]


_PROVIDER_TO_MODELS_MAP = {
    OPENAI_PROVIDER_NAME: OPEN_AI_MODEL_NAMES,
    BEDROCK_PROVIDER_NAME: BEDROCK_MODEL_NAMES,
    ANTHROPIC_PROVIDER_NAME: ANTHROPIC_MODEL_NAMES,
    VERTEXAI_PROVIDER_NAME: VERTEXAI_MODEL_NAMES,
}

_PROVIDER_TO_VISIBLE_MODELS_MAP: dict[str, list[str]] = {
    OPENAI_PROVIDER_NAME: OPEN_AI_VISIBLE_MODEL_NAMES,
    BEDROCK_PROVIDER_NAME: [
        model["name"]
        for model in curated_models.get("bedrock", [])
        if model.get("recommended_is_visible", False)
        and not model.get("deprecated", False)
    ],
    ANTHROPIC_PROVIDER_NAME: ANTHROPIC_VISIBLE_MODEL_NAMES,
    VERTEXAI_PROVIDER_NAME: VERTEXAI_VISIBLE_MODEL_NAMES,
}


def fetch_available_well_known_llms() -> list[WellKnownLLMProviderDescriptor]:
    return [
        WellKnownLLMProviderDescriptor(
            name=OPENAI_PROVIDER_NAME,
            display_name="OpenAI",
            api_key_required=True,
            api_base_required=False,
            api_version_required=False,
            custom_config_keys=[],
            model_configurations=fetch_model_configurations_for_provider(
                OPENAI_PROVIDER_NAME
            ),
            default_model=get_curated_recommended_default_model(OPENAI_PROVIDER_NAME),
            default_fast_model=get_curated_recommended_fast_default_model(
                OPENAI_PROVIDER_NAME
            ),
            has_curated_models=OPENAI_PROVIDER_NAME in curated_models,
        ),
        WellKnownLLMProviderDescriptor(
            name=ANTHROPIC_PROVIDER_NAME,
            display_name="Anthropic",
            api_key_required=True,
            api_base_required=False,
            api_version_required=False,
            custom_config_keys=[],
            model_configurations=fetch_model_configurations_for_provider(
                ANTHROPIC_PROVIDER_NAME
            ),
            default_model=get_curated_recommended_default_model(
                ANTHROPIC_PROVIDER_NAME
            ),
            default_fast_model=get_curated_recommended_fast_default_model(
                ANTHROPIC_PROVIDER_NAME
            ),
            has_curated_models=ANTHROPIC_PROVIDER_NAME in curated_models,
        ),
        WellKnownLLMProviderDescriptor(
            name=AZURE_PROVIDER_NAME,
            display_name="Azure OpenAI",
            api_key_required=True,
            api_base_required=True,
            api_version_required=True,
            custom_config_keys=[],
            model_configurations=fetch_model_configurations_for_provider(
                AZURE_PROVIDER_NAME
            ),
            deployment_name_required=True,
            single_model_supported=True,
            has_curated_models=AZURE_PROVIDER_NAME in curated_models,
        ),
        WellKnownLLMProviderDescriptor(
            name=BEDROCK_PROVIDER_NAME,
            display_name="AWS Bedrock",
            api_key_required=False,
            api_base_required=False,
            api_version_required=False,
            custom_config_keys=[
                CustomConfigKey(
                    name="AWS_REGION_NAME",
                    display_name="AWS Region Name",
                ),
                CustomConfigKey(
                    name="AWS_ACCESS_KEY_ID",
                    display_name="AWS Access Key ID",
                    is_required=False,
                    description="If using AWS IAM roles, AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY can be left blank.",
                ),
                CustomConfigKey(
                    name="AWS_SECRET_ACCESS_KEY",
                    display_name="AWS Secret Access Key",
                    is_required=False,
                    is_secret=True,
                    description="If using AWS IAM roles, AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY can be left blank.",
                ),
            ],
            model_configurations=fetch_model_configurations_for_provider(
                BEDROCK_PROVIDER_NAME
            ),
            default_model=get_curated_recommended_default_model(BEDROCK_PROVIDER_NAME),
            default_fast_model=get_curated_recommended_fast_default_model(
                BEDROCK_PROVIDER_NAME
            ),
            has_curated_models=BEDROCK_PROVIDER_NAME in curated_models,
        ),
        WellKnownLLMProviderDescriptor(
            name=VERTEXAI_PROVIDER_NAME,
            display_name="GCP Vertex AI",
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
                    "[Vertex AI configuration docs](https://docs.onyx.app/gen_ai_configs/vertex_ai) for all possible values.",
                    is_required=False,
                    is_secret=False,
                    key_type=CustomConfigKeyType.TEXT_INPUT,
                    default_value="us-east1",
                ),
            ],
            default_model=get_curated_recommended_default_model(VERTEXAI_PROVIDER_NAME),
            default_fast_model=get_curated_recommended_fast_default_model(
                VERTEXAI_PROVIDER_NAME
            ),
            has_curated_models=VERTEXAI_PROVIDER_NAME in curated_models,
        ),
    ]


def fetch_models_for_provider(provider_name: str) -> list[str]:
    return _PROVIDER_TO_MODELS_MAP.get(provider_name, [])


def fetch_model_names_for_provider_as_set(provider_name: str) -> set[str] | None:
    model_names = fetch_models_for_provider(provider_name)
    return set(model_names) if model_names else None


def fetch_visible_model_names_for_provider_as_set(
    provider_name: str,
) -> set[str] | None:
    visible_model_names: list[str] | None = _PROVIDER_TO_VISIBLE_MODELS_MAP.get(
        provider_name
    )
    return set(visible_model_names) if visible_model_names else None


def fetch_model_configurations_for_provider(
    provider_name: str,
    include_deprecated: bool = False,
) -> list[ModelConfigurationView]:
    # Use curated_models to determine which models should be visible
    # If a model is in curated_models, use its recommended_is_visible value
    # Otherwise, fall back to the old logic for backward compatibility
    return [
        ModelConfigurationView(
            name=model["name"],
            is_visible=get_curated_is_visible(provider_name, model["name"]),
            max_input_tokens=None,
            supports_image_input=model_supports_image_input(
                model_name=model["name"],
                model_provider=provider_name,
            ),
        )
        for model in curated_models.get(provider_name, [])
        if include_deprecated
        or not model.get(
            "deprecated", False
        )  # Filter out deprecated models unless include_deprecated is True
    ]


def fetch_all_model_configurations_for_provider(
    provider_name: str,
) -> list[ModelConfigurationView]:
    """Fetch all model configurations for a provider, including deprecated ones."""
    return fetch_model_configurations_for_provider(
        provider_name, include_deprecated=True
    )
