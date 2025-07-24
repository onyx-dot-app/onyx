from enum import Enum

import litellm  # type: ignore
from pydantic import BaseModel

from onyx.llm.utils import model_supports_image_input
from onyx.server.manage.llm.models import ModelConfigurationView


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


OPENAI_PROVIDER_NAME = "openai"
OPEN_AI_MODEL_NAMES = [
    "o4-mini",
    "o3-mini",
    "o1-mini",
    "o3",
    "o1",
    "gpt-4",
    "gpt-4.1",
    "gpt-4o",
    "gpt-4o-mini",
    "o1-preview",
    "gpt-4-turbo",
    "gpt-4-turbo-preview",
    "gpt-4-1106-preview",
    "gpt-4-vision-preview",
    "gpt-4-0613",
    "gpt-4o-2024-08-06",
    "gpt-4-0314",
    "gpt-4-32k-0314",
    "gpt-3.5-turbo",
    "gpt-3.5-turbo-0125",
    "gpt-3.5-turbo-1106",
    "gpt-3.5-turbo-16k",
    "gpt-3.5-turbo-0613",
    "gpt-3.5-turbo-16k-0613",
    "gpt-3.5-turbo-0301",
]
OPEN_AI_VISIBLE_MODEL_NAMES = ["o1", "o3-mini", "gpt-4o", "gpt-4o-mini"]

BEDROCK_PROVIDER_NAME = "bedrock"
# need to remove all the weird "bedrock/eu-central-1/anthropic.claude-v1" named
# models
BEDROCK_MODEL_NAMES = [
    model
    # bedrock_converse_models are just extensions of the bedrock_models, not sure why
    # litellm has split them into two lists :(
    for model in litellm.bedrock_models + litellm.bedrock_converse_models
    if "/" not in model and "embed" not in model
][::-1]
BEDROCK_DEFAULT_MODEL = "anthropic.claude-3-5-sonnet-20241022-v2:0"

IGNORABLE_ANTHROPIC_MODELS = [
    "claude-2",
    "claude-instant-1",
    "anthropic/claude-3-5-sonnet-20241022",
]
ANTHROPIC_PROVIDER_NAME = "anthropic"
ANTHROPIC_MODEL_NAMES = [
    model
    for model in litellm.anthropic_models
    if model not in IGNORABLE_ANTHROPIC_MODELS
][::-1]
ANTHROPIC_VISIBLE_MODEL_NAMES = [
    "claude-3-5-sonnet-20241022",
    "claude-3-7-sonnet-20250219",
]

AZURE_PROVIDER_NAME = "azure"


VERTEXAI_PROVIDER_NAME = "vertex_ai"
VERTEXAI_DEFAULT_MODEL = "gemini-2.0-flash"
VERTEXAI_DEFAULT_FAST_MODEL = "gemini-2.0-flash-lite"
VERTEXAI_MODEL_NAMES = [
    # 2.5 pro models
    "gemini-2.5-pro-preview-06-05",
    "gemini-2.5-pro-preview-05-06",
    # 2.0 flash-lite models
    VERTEXAI_DEFAULT_FAST_MODEL,
    "gemini-2.0-flash-lite-001",
    # "gemini-2.0-flash-lite-preview-02-05",
    # 2.0 flash models
    VERTEXAI_DEFAULT_MODEL,
    "gemini-2.0-flash-001",
    "gemini-2.0-flash-exp",
    # "gemini-2.0-flash-exp-image-generation",
    # "gemini-2.0-flash-thinking-exp-01-21",
    # 1.5 pro models
    "gemini-1.5-pro",
    "gemini-1.5-pro-001",
    "gemini-1.5-pro-002",
    # 1.5 flash models
    "gemini-1.5-flash",
    "gemini-1.5-flash-001",
    "gemini-1.5-flash-002",
    # Anthropic models
    "claude-sonnet-4",
    "claude-opus-4",
    "claude-3-7-sonnet@20250219",
]
VERTEXAI_VISIBLE_MODEL_NAMES = [
    VERTEXAI_DEFAULT_MODEL,
    VERTEXAI_DEFAULT_FAST_MODEL,
]


_PROVIDER_TO_MODELS_MAP = {
    OPENAI_PROVIDER_NAME: OPEN_AI_MODEL_NAMES,
    BEDROCK_PROVIDER_NAME: BEDROCK_MODEL_NAMES,
    ANTHROPIC_PROVIDER_NAME: ANTHROPIC_MODEL_NAMES,
    VERTEXAI_PROVIDER_NAME: VERTEXAI_MODEL_NAMES,
}

_PROVIDER_TO_VISIBLE_MODELS_MAP = {
    OPENAI_PROVIDER_NAME: OPEN_AI_VISIBLE_MODEL_NAMES,
    BEDROCK_PROVIDER_NAME: [BEDROCK_DEFAULT_MODEL],
    ANTHROPIC_PROVIDER_NAME: ANTHROPIC_VISIBLE_MODEL_NAMES,
    VERTEXAI_PROVIDER_NAME: VERTEXAI_VISIBLE_MODEL_NAMES,
}


CREDENTIALS_FILE_CUSTOM_CONFIG_KEY = "CREDENTIALS_FILE"


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
            default_model="gpt-4o",
            default_fast_model="gpt-4o-mini",
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
            default_model="claude-3-7-sonnet-20250219",
            default_fast_model="claude-3-5-sonnet-20241022",
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
            default_model=BEDROCK_DEFAULT_MODEL,
            default_fast_model=BEDROCK_DEFAULT_MODEL,
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
                    name=CREDENTIALS_FILE_CUSTOM_CONFIG_KEY,
                    display_name="Credentials File",
                    description="This should be a JSON file containing some private credentials.",
                    is_required=True,
                    is_secret=False,
                    key_type=CustomConfigKeyType.FILE_INPUT,
                ),
            ],
            default_model=VERTEXAI_DEFAULT_MODEL,
            default_fast_model=VERTEXAI_DEFAULT_MODEL,
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
) -> list[ModelConfigurationView]:
    # if there are no explicitly listed visible model names,
    # then we won't mark any of them as "visible". This will get taken
    # care of by the logic to make default models visible.
    visible_model_names = (
        fetch_visible_model_names_for_provider_as_set(provider_name) or set()
    )
    return [
        ModelConfigurationView(
            name=model_name,
            is_visible=model_name in visible_model_names,
            max_input_tokens=None,
            supports_image_input=model_supports_image_input(
                model_name=model_name,
                model_provider=provider_name,
            ),
        )
        for model_name in fetch_models_for_provider(provider_name)
    ]
