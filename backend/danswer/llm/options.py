import litellm  # type: ignore
from pydantic import BaseModel


class CustomConfigKey(BaseModel):
    name: str
    description: str | None = None
    is_required: bool = True
    is_secret: bool = False


class WellKnownLLMProviderDescriptor(BaseModel):
    name: str
    display_name: str | None = None
    api_key_required: bool
    api_base_required: bool
    api_version_required: bool
    custom_config_keys: list[CustomConfigKey] | None = None

    llm_names: list[str]
    default_model: str | None = None
    default_fast_model: str | None = None


OPENAI_PROVIDER_NAME = "openai"
OPEN_AI_MODEL_NAMES = [
    "gpt-4",
    "gpt-4-turbo",
    "gpt-4-turbo-preview",
    "gpt-4-1106-preview",
    "gpt-4-vision-preview",
    "gpt-4-32k",
    "gpt-4-0613",
    "gpt-4-32k-0613",
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
BEDROCK_MODEL_NAMES = [model for model in litellm.bedrock_models if "/" not in model][
    ::-1
]

ANTHROPIC_PROVIDER_NAME = "anthropic"
ANTHROPIC_MODEL_NAMES = [model for model in litellm.anthropic_models][::-1]

AZURE_PROVIDER_NAME = "azure"


_PROVIDER_TO_MODELS_MAP = {
    OPENAI_PROVIDER_NAME: OPEN_AI_MODEL_NAMES,
    BEDROCK_PROVIDER_NAME: BEDROCK_MODEL_NAMES,
    ANTHROPIC_PROVIDER_NAME: ANTHROPIC_MODEL_NAMES,
}


def fetch_available_well_known_llms() -> list[WellKnownLLMProviderDescriptor]:
    return [
        WellKnownLLMProviderDescriptor(
            name="openai",
            display_name="OpenAI",
            api_key_required=True,
            api_base_required=False,
            api_version_required=False,
            custom_config_keys=[],
            llm_names=fetch_models_for_provider("openai"),
            default_model="gpt-4",
            default_fast_model="gpt-3.5-turbo",
        ),
        WellKnownLLMProviderDescriptor(
            name=ANTHROPIC_PROVIDER_NAME,
            display_name="Anthropic",
            api_key_required=True,
            api_base_required=False,
            api_version_required=False,
            custom_config_keys=[],
            llm_names=fetch_models_for_provider(ANTHROPIC_PROVIDER_NAME),
            default_model="claude-3-opus-20240229",
            default_fast_model="claude-3-sonnet-20240229",
        ),
        WellKnownLLMProviderDescriptor(
            name=AZURE_PROVIDER_NAME,
            display_name="Azure OpenAI",
            api_key_required=True,
            api_base_required=True,
            api_version_required=True,
            custom_config_keys=[],
            llm_names=fetch_models_for_provider(AZURE_PROVIDER_NAME),
        ),
        WellKnownLLMProviderDescriptor(
            name=BEDROCK_PROVIDER_NAME,
            display_name="AWS Bedrock",
            api_key_required=False,
            api_base_required=False,
            api_version_required=False,
            custom_config_keys=[
                CustomConfigKey(name="AWS_REGION_NAME"),
                CustomConfigKey(
                    name="AWS_ACCESS_KEY_ID",
                    is_required=False,
                    description="If using AWS IAM roles, AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY can be left blank.",
                ),
                CustomConfigKey(
                    name="AWS_SECRET_ACCESS_KEY",
                    is_required=False,
                    is_secret=True,
                    description="If using AWS IAM roles, AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY can be left blank.",
                ),
            ],
            llm_names=fetch_models_for_provider(BEDROCK_PROVIDER_NAME),
            default_model="anthropic.claude-3-sonnet-20240229-v1:0",
            default_fast_model="anthropic.claude-3-haiku-20240307-v1:0",
        ),
    ]


def fetch_models_for_provider(provider_name: str) -> list[str]:
    return _PROVIDER_TO_MODELS_MAP.get(provider_name, [])
