from onyx.llm.constants import LlmProviderNames

OPENAI_PROVIDER_NAME = "openai"

BEDROCK_PROVIDER_NAME = "bedrock"


OLLAMA_PROVIDER_NAME = "ollama_chat"
OLLAMA_API_KEY_CONFIG_KEY = "OLLAMA_API_KEY"

LM_STUDIO_PROVIDER_NAME = "lm_studio"
LM_STUDIO_API_KEY_CONFIG_KEY = "LM_STUDIO_API_KEY"

LITELLM_PROXY_PROVIDER_NAME = "litellm_proxy"

BIFROST_PROVIDER_NAME = "bifrost"

OPENAI_COMPATIBLE_PROVIDER_NAME = "openai_compatible"

NEBIUS_TOKENFACTORY_PROVIDER_NAME = "nebius_tokenfactory"

PORTKEY_PROVIDER_NAME = "portkey"
# custom_config key that records which Portkey API surface a provider targets.
PORTKEY_API_MODE_CONFIG_KEY = "portkey_api_mode"
# OpenAI-compatible Chat Completions surface (default). Base ends in /v1.
PORTKEY_API_MODE_CHAT_COMPLETIONS = "chat_completions"
# OpenAI-compatible Responses surface. Base ends in /v1; model gets a responses/ prefix.
PORTKEY_API_MODE_RESPONSES = "responses"
# Anthropic-compatible Messages surface. Base stays bare; litellm appends /v1/messages.
PORTKEY_API_MODE_MESSAGES = "messages"
PORTKEY_DEFAULT_API_MODE = PORTKEY_API_MODE_CHAT_COMPLETIONS
# Base URLs differ by surface: OpenAI-compat modes use /v1, Messages uses the bare host.
PORTKEY_DEFAULT_API_BASE_OPENAI = "https://api.portkey.ai/v1"
PORTKEY_DEFAULT_API_BASE_ANTHROPIC = "https://api.portkey.ai"

# Providers that use optional Bearer auth from custom_config
PROVIDERS_WITH_SPECIAL_API_KEY_HANDLING: dict[str, str] = {
    LlmProviderNames.OLLAMA_CHAT: OLLAMA_API_KEY_CONFIG_KEY,
    LlmProviderNames.LM_STUDIO: LM_STUDIO_API_KEY_CONFIG_KEY,
}

# OpenRouter
OPENROUTER_PROVIDER_NAME = "openrouter"

ANTHROPIC_PROVIDER_NAME = "anthropic"

AZURE_PROVIDER_NAME = "azure"


VERTEXAI_PROVIDER_NAME = "vertex_ai"
VERTEX_CREDENTIALS_FILE_KWARG = "vertex_credentials"
VERTEX_CREDENTIALS_FILE_KWARG_ENV_VAR_FORMAT = "CREDENTIALS_FILE"
VERTEX_LOCATION_KWARG = "vertex_location"
VERTEX_PROJECT_KWARG = "vertex_project"

VERTEX_AUTH_METHOD_KWARG = "vertex_auth_method"
VERTEX_AUTH_METHOD_SERVICE_ACCOUNT = "service_account_json"
VERTEX_AUTH_METHOD_WORKLOAD_IDENTITY = "workload_identity"

AWS_REGION_NAME_KWARG = "aws_region_name"
AWS_REGION_NAME_KWARG_ENV_VAR_FORMAT = "AWS_REGION_NAME"
AWS_BEARER_TOKEN_BEDROCK_KWARG_ENV_VAR_FORMAT = "AWS_BEARER_TOKEN_BEDROCK"
AWS_ACCESS_KEY_ID_KWARG = "aws_access_key_id"
AWS_ACCESS_KEY_ID_KWARG_ENV_VAR_FORMAT = "AWS_ACCESS_KEY_ID"
AWS_SECRET_ACCESS_KEY_KWARG = "aws_secret_access_key"
AWS_SECRET_ACCESS_KEY_KWARG_ENV_VAR_FORMAT = "AWS_SECRET_ACCESS_KEY"
