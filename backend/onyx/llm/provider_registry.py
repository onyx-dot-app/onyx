"""Provider routes supported by the native model factory."""

from onyx.llm.constants import LlmProviderNames

COMPATIBLE_NATIVE_PROVIDERS = {
    "deepseek": "deepseek",
    "nebius_tokenfactory": "nebius",
    "together_ai": "together",
    "fireworks_ai": "fireworks",
    "cerebras": "cerebras",
    "sambanova": "sambanova",
    "ovhcloud": "ovhcloud",
    "moonshot": "moonshotai",
    "alibaba": "alibaba",
}

OPENAI_COMPATIBLE_BASE_URLS = {
    "lm_studio": "http://localhost:1234/v1",
    "xai": "https://api.x.ai/v1",
}

SUPPORTED_PROVIDER_NAMES = frozenset(
    {provider.value for provider in LlmProviderNames}
    | COMPATIBLE_NATIVE_PROVIDERS.keys()
    | OPENAI_COMPATIBLE_BASE_URLS.keys()
    | {"gemini", "groq", "cohere", "cohere_chat"}
)
