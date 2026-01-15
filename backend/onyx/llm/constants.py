"""
LLM Constants

Centralized constants for LLM providers, vendors, and display names.
"""

from enum import Enum


# Provider names
class LlmProviderNames(str, Enum):
    """
    Canonical string identifiers for LLM providers.
    """

    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"
    BEDROCK = "bedrock"
    BEDROCK_CONVERSE = "bedrock_converse"
    VERTEX_AI = "vertex_ai"
    OPENROUTER = "openrouter"
    AZURE = "azure"
    OLLAMA_CHAT = "ollama_chat"
    MISTRAL = "mistral"
    LITELLM_PROXY = "litellm_proxy"

    def __str__(self) -> str:
        """Needed so things like:

        f"{LlmProviderNames.OPENAI}/" gives back "openai/" instead of "LlmProviderNames.OPENAI/"
        """
        return self.value


WELL_KNOWN_PROVIDER_NAMES = [
    LlmProviderNames.OPENAI,
    LlmProviderNames.ANTHROPIC,
    LlmProviderNames.VERTEX_AI,
    LlmProviderNames.BEDROCK,
    LlmProviderNames.OPENROUTER,
    LlmProviderNames.AZURE,
    LlmProviderNames.OLLAMA_CHAT,
]


# Proper capitalization for known providers and vendors
PROVIDER_DISPLAY_NAMES: dict[str, str] = {
    LlmProviderNames.OPENAI: "OpenAI",
    LlmProviderNames.ANTHROPIC: "Anthropic",
    LlmProviderNames.GOOGLE: "Google",
    LlmProviderNames.BEDROCK: "Bedrock",
    LlmProviderNames.BEDROCK_CONVERSE: "Bedrock",
    LlmProviderNames.VERTEX_AI: "Vertex AI",
    LlmProviderNames.OPENROUTER: "OpenRouter",
    LlmProviderNames.AZURE: "Azure",
    "ollama": "Ollama",
    LlmProviderNames.OLLAMA_CHAT: "Ollama",
    "groq": "Groq",
    "anyscale": "Anyscale",
    "deepseek": "DeepSeek",
    "xai": "xAI",
    LlmProviderNames.MISTRAL: "Mistral",
    "mistralai": "Mistral",  # Alias used by some providers
    "cohere": "Cohere",
    "perplexity": "Perplexity",
    "amazon": "Amazon",
    "meta": "Meta",
    "meta-llama": "Meta",  # Alias used by some providers
    "ai21": "AI21",
    "nvidia": "NVIDIA",
    "databricks": "Databricks",
    "alibaba": "Alibaba",
    "qwen": "Qwen",
    "microsoft": "Microsoft",
    "gemini": "Gemini",
    "stability": "Stability",
    "writer": "Writer",
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
    "ai21": "Jamba",
    "nvidia": "Nemotron",
    "qwen": "Qwen",
    "alibaba": "Qwen",
    "writer": "Palmyra",
}

# Aggregator providers that host models from multiple vendors
AGGREGATOR_PROVIDERS: set[str] = {
    LlmProviderNames.BEDROCK,
    LlmProviderNames.BEDROCK_CONVERSE,
    LlmProviderNames.OPENROUTER,
    LlmProviderNames.OLLAMA_CHAT,
    LlmProviderNames.VERTEX_AI,
    LlmProviderNames.AZURE,
}

# Model family name mappings for display name generation
# Used by Bedrock display name generator
BEDROCK_MODEL_NAME_MAPPINGS: dict[str, str] = {
    "claude": "Claude",
    "llama": "Llama",
    "mistral": "Mistral",
    "mixtral": "Mixtral",
    "titan": "Titan",
    "nova": "Nova",
    "jamba": "Jamba",
    "command": "Command",
    "deepseek": "DeepSeek",
}

# Used by Ollama display name generator
OLLAMA_MODEL_NAME_MAPPINGS: dict[str, str] = {
    "llama": "Llama",
    "qwen": "Qwen",
    "mistral": "Mistral",
    "deepseek": "DeepSeek",
    "gemma": "Gemma",
    "phi": "Phi",
    "codellama": "Code Llama",
    "starcoder": "StarCoder",
    "wizardcoder": "WizardCoder",
    "vicuna": "Vicuna",
    "orca": "Orca",
    "dolphin": "Dolphin",
    "nous": "Nous",
    "neural": "Neural",
    "mixtral": "Mixtral",
    "falcon": "Falcon",
    "yi": "Yi",
    "command": "Command",
    "zephyr": "Zephyr",
    "openchat": "OpenChat",
    "solar": "Solar",
}

# Bedrock model token limits (AWS doesn't expose this via API)
# Note: Many Bedrock model IDs include context length suffix (e.g., ":200k")
# which is parsed first. This mapping is for models without suffixes.
# Sources:
# - LiteLLM model_prices_and_context_window.json
# - AWS Bedrock documentation and announcement blogs
BEDROCK_MODEL_TOKEN_LIMITS: dict[str, int] = {
    # Anthropic Claude models (new naming: claude-{tier}-{version})
    "claude-opus-4": 200000,
    "claude-sonnet-4": 200000,
    "claude-haiku-4": 200000,
    # Anthropic Claude models (old naming: claude-{version})
    "claude-4": 200000,
    "claude-3-7": 200000,
    "claude-3-5": 200000,
    "claude-3": 200000,
    "claude-v2": 100000,
    "claude-instant": 100000,
    # Amazon Nova models (from LiteLLM)
    "nova-premier": 1000000,
    "nova-pro": 300000,
    "nova-lite": 300000,
    "nova-2-lite": 1000000,  # Nova 2 Lite has 1M context
    "nova-2-sonic": 128000,
    "nova-micro": 128000,
    # Amazon Titan models (from LiteLLM: all text models are 42K)
    "titan-text-premier": 42000,
    "titan-text-express": 42000,
    "titan-text-lite": 42000,
    "titan-tg1": 8000,
    # Meta Llama models (Llama 3 base = 8K, Llama 3.1+ = 128K)
    "llama4": 128000,
    "llama3-3": 128000,
    "llama3-2": 128000,
    "llama3-1": 128000,
    "llama3-8b": 8000,
    "llama3-70b": 8000,
    # Mistral models (Large 2+ = 128K, original Large/Small = 32K)
    "mistral-large-3": 128000,
    "mistral-large-2407": 128000,  # Mistral Large 2
    "mistral-large-2402": 32000,  # Original Mistral Large
    "mistral-large": 128000,  # Default to newer version
    "mistral-small": 32000,
    "mistral-7b": 32000,
    "mixtral-8x7b": 32000,
    "pixtral": 128000,
    "ministral": 128000,
    "magistral": 128000,
    "voxtral": 32000,
    # Cohere models
    "command-r-plus": 128000,
    "command-r": 128000,
    # DeepSeek models
    "deepseek": 64000,
    # Google Gemma models
    "gemma-3": 128000,
    "gemma-2": 8000,
    "gemma": 8000,
    # Qwen models
    "qwen3": 128000,
    "qwen2": 128000,
    # NVIDIA models
    "nemotron": 128000,
    # Writer Palmyra models
    "palmyra": 128000,
    # Moonshot Kimi
    "kimi": 128000,
    # Minimax
    "minimax": 128000,
    # OpenAI (via Bedrock)
    "gpt-oss": 128000,
    # AI21 models (from LiteLLM: Jamba 1.5 = 256K, Jamba Instruct = 70K)
    "jamba-1-5": 256000,
    "jamba-instruct": 70000,
    "jamba": 256000,  # Default to newer version
}


# Models that should keep their hyphenated format in display names
# These are model families where the hyphen is part of the brand name
HYPHENATED_MODEL_NAMES: set[str] = {
    "gpt-oss",
}


# General model prefix to vendor mapping (used as fallback when enrichment data is missing)
# This covers common model families across all providers
MODEL_PREFIX_TO_VENDOR: dict[str, str] = {
    # Google
    "gemini": "google",
    "gemma": "google",
    "palm": "google",
    # Anthropic
    "claude": "anthropic",
    # OpenAI
    "gpt": "openai",
    "o1": "openai",
    "o3": "openai",
    "o4": "openai",
    "chatgpt": "openai",
    # Meta
    "llama": "meta",
    "codellama": "meta",
    # Mistral
    "mistral": "mistral",
    "mixtral": "mistral",
    "codestral": "mistral",
    "ministral": "mistral",
    "pixtral": "mistral",
    "magistral": "mistral",
    # Cohere
    "command": "cohere",
    "aya": "cohere",
    # Amazon
    "nova": "amazon",
    "titan": "amazon",
    # AI21
    "jamba": "ai21",
    # DeepSeek
    "deepseek": "deepseek",
    # Alibaba/Qwen
    "qwen": "alibaba",
    "qwq": "alibaba",
    # Microsoft
    "phi": "microsoft",
    # NVIDIA
    "nemotron": "nvidia",
    # xAI
    "grok": "xai",
}


# Ollama model prefix to vendor mapping (for grouping models by vendor)
OLLAMA_MODEL_TO_VENDOR: dict[str, str] = {
    "llama": "Meta",
    "codellama": "Meta",
    "qwen": "Alibaba",
    "qwq": "Alibaba",
    "mistral": "Mistral",
    "ministral": "Mistral",
    "mixtral": "Mistral",
    "deepseek": "DeepSeek",
    "gemma": "Google",
    "phi": "Microsoft",
    "command": "Cohere",
    "aya": "Cohere",
    "falcon": "TII",
    "yi": "01.AI",
    "starcoder": "BigCode",
    "wizardcoder": "WizardLM",
    "vicuna": "LMSYS",
    "openchat": "OpenChat",
    "solar": "Upstage",
    "orca": "Microsoft",
    "dolphin": "Cognitive Computations",
    "nous": "Nous Research",
    "neural": "Intel",
    "zephyr": "HuggingFace",
    "granite": "IBM",
    "nemotron": "NVIDIA",
    "smollm": "HuggingFace",
}
