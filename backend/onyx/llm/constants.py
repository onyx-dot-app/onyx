"""
LLM Constants

Centralized constants for LLM providers, vendors, and display names.
"""

# Proper capitalization for known providers and vendors
PROVIDER_DISPLAY_NAMES: dict[str, str] = {
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "google": "Google",
    "bedrock": "Bedrock",
    "bedrock_converse": "Bedrock",
    "vertex_ai": "Vertex AI",
    "openrouter": "OpenRouter",
    "azure": "Azure",
    "ollama": "Ollama",
    "ollama_chat": "Ollama",
    "groq": "Groq",
    "anyscale": "Anyscale",
    "deepseek": "DeepSeek",
    "xai": "xAI",
    "mistral": "Mistral",
    "cohere": "Cohere",
    "perplexity": "Perplexity",
    "amazon": "Amazon",
    "meta": "Meta",
    "ai21": "AI21",
    "nvidia": "NVIDIA",
    "databricks": "Databricks",
    "alibaba": "Alibaba",
    "microsoft": "Microsoft",
    "gemini": "Gemini",
}

# Map vendors to their brand names (used for provider_display_name generation)
VENDOR_BRAND_NAMES: dict[str, str] = {
    "anthropic": "Claude",
    "openai": "GPT",
    "google": "Gemini",
    "amazon": "Nova",
    "meta": "Llama",
    "mistral": "Mistral",
    "cohere": "Command",
    "deepseek": "DeepSeek",
    "xai": "Grok",
    "perplexity": "Sonar",
}

# Aggregator providers that host models from multiple vendors
AGGREGATOR_PROVIDERS: set[str] = {
    "bedrock",
    "bedrock_converse",
    "openrouter",
    "vertex_ai",
    "azure",
}
