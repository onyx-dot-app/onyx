OPENAI_PROVIDER_NAME = "openai"
# Curated list of OpenAI models to show by default in the UI
OPENAI_VISIBLE_MODEL_NAMES = {
    "gpt-5",
    "gpt-5-mini",
    "o1",
    "o3-mini",
    "gpt-4o",
    "gpt-4o-mini",
}

BEDROCK_PROVIDER_NAME = "bedrock"
BEDROCK_DEFAULT_MODEL = "anthropic.claude-3-5-sonnet-20241022-v2:0"


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


OLLAMA_PROVIDER_NAME = "ollama_chat"
OLLAMA_API_KEY_CONFIG_KEY = "OLLAMA_API_KEY"

# OpenRouter
OPENROUTER_PROVIDER_NAME = "openrouter"

ANTHROPIC_PROVIDER_NAME = "anthropic"

# Curated list of Anthropic models to show by default in the UI
ANTHROPIC_VISIBLE_MODEL_NAMES = {
    "claude-opus-4-5",
    "claude-sonnet-4-5",
    "claude-haiku-4-5",
}

AZURE_PROVIDER_NAME = "azure"


VERTEXAI_PROVIDER_NAME = "vertex_ai"
VERTEX_CREDENTIALS_FILE_KWARG = "vertex_credentials"
VERTEX_LOCATION_KWARG = "vertex_location"
VERTEXAI_DEFAULT_MODEL = "gemini-2.5-flash"
# Curated list of Vertex AI models to show by default in the UI
VERTEXAI_VISIBLE_MODEL_NAMES = {
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.5-pro",
}
