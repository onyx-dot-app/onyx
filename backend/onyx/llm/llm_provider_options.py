from enum import Enum

import litellm  # type: ignore
from pydantic import BaseModel


class CustomConfigKeyType(Enum):
    # used for configuration values that require manual input
    # i.e., textual API keys (e.g., "abcd1234")
    TEXT_INPUT = "text_input"

    # used for configuration values that require a file to be select/drag-and-dropped
    # i.e., file based credentials (e.g., "/path/to/credentials/file.json")
    DRAG_AND_DROP = "drag_and_drop"


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
    llm_names: list[str]
    default_model: str | None = None
    default_fast_model: str | None = None
    # set for providers like Azure, which require a deployment name.
    deployment_name_required: bool = False
    # set for providers like Azure, which support a single model per deployment.
    single_model_supported: bool = False


OPENAI_PROVIDER_NAME = "openai"
OPEN_AI_MODEL_NAMES = [
    "o3-mini",
    "o1-mini",
    "o1",
    "gpt-4",
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

AZURE_PROVIDER_NAME = "azure"


VERTEXAI_PROVIDER_NAME = "vertexai"
VERTEXAI_DEFAULT_MODEL = "gemini-1.5-pro-002"
VERTEXAI_MODEL_NAMES = [
    VERTEXAI_DEFAULT_MODEL,
]


_PROVIDER_TO_MODELS_MAP = {
    OPENAI_PROVIDER_NAME: OPEN_AI_MODEL_NAMES,
    BEDROCK_PROVIDER_NAME: BEDROCK_MODEL_NAMES,
    ANTHROPIC_PROVIDER_NAME: ANTHROPIC_MODEL_NAMES,
    VERTEXAI_PROVIDER_NAME: VERTEXAI_MODEL_NAMES,
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
            llm_names=fetch_models_for_provider(OPENAI_PROVIDER_NAME),
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
            llm_names=fetch_models_for_provider(ANTHROPIC_PROVIDER_NAME),
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
            llm_names=fetch_models_for_provider(AZURE_PROVIDER_NAME),
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
            llm_names=fetch_models_for_provider(BEDROCK_PROVIDER_NAME),
            default_model="anthropic.claude-3-5-sonnet-20241022-v2:0",
            default_fast_model="anthropic.claude-3-5-sonnet-20241022-v2:0",
        ),
        WellKnownLLMProviderDescriptor(
            name=VERTEXAI_PROVIDER_NAME,
            display_name="Gemini",
            api_key_required=False,
            api_base_required=False,
            api_version_required=False,
            llm_names=fetch_models_for_provider(VERTEXAI_PROVIDER_NAME),
            custom_config_keys=[
                CustomConfigKey(
                    name="CREDENTIALS_FILE",
                    display_name="Credentials File",
                    description="This should be a JSON file containing some private credentials.",
                    is_required=True,
                    is_secret=False,
                    key_type=CustomConfigKeyType.DRAG_AND_DROP,
                ),
            ],
            default_model=VERTEXAI_DEFAULT_MODEL,
            default_fast_model=VERTEXAI_DEFAULT_MODEL,
        ),
    ]


def fetch_models_for_provider(provider_name: str) -> list[str]:
    return _PROVIDER_TO_MODELS_MAP.get(provider_name, [])
