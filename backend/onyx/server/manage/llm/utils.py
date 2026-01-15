"""
LLM Provider Utilities

Utilities for dynamic LLM providers (Bedrock, Ollama, OpenRouter):
- Display name generation from model identifiers
- Model validation and filtering
- Vision/reasoning capability inference
"""

import re
from typing import TypedDict

from onyx.llm.constants import BEDROCK_MODEL_NAME_MAPPINGS
from onyx.llm.constants import LlmProviderNames
from onyx.llm.constants import OLLAMA_MODEL_NAME_MAPPINGS
from onyx.llm.constants import OLLAMA_MODEL_TO_VENDOR
from onyx.llm.constants import PROVIDER_DISPLAY_NAMES


# Dynamic providers fetch models directly from source APIs (not LiteLLM)
DYNAMIC_LLM_PROVIDERS = frozenset(
    {
        LlmProviderNames.OPENROUTER,
        LlmProviderNames.BEDROCK,
        LlmProviderNames.OLLAMA_CHAT,
    }
)


class ModelMetadata(TypedDict):
    """Metadata about a model from the provider API."""

    display_name: str
    supports_image_input: bool


# Non-LLM model patterns to filter out (image gen, embeddings, etc.)
NON_LLM_PATTERNS = frozenset({"embed", "stable-", "titan-image", "titan-embed"})

# Known Bedrock vision-capable models (for fallback when base model not in region)
BEDROCK_VISION_MODELS = frozenset(
    {
        "anthropic.claude-3",
        "anthropic.claude-4",
        "amazon.nova-pro",
        "amazon.nova-lite",
        "amazon.nova-premier",
    }
)


def is_valid_bedrock_model(
    model_id: str,
    supports_streaming: bool = True,
) -> bool:
    """Check if a Bedrock model ID is a valid LLM model.

    Args:
        model_id: The model ID to check
        supports_streaming: Whether the model supports streaming (required for LLMs)

    Returns:
        True if the model is a valid LLM, False otherwise
    """
    if not model_id:
        return False
    if any(pattern in model_id.lower() for pattern in NON_LLM_PATTERNS):
        return False
    if not supports_streaming:
        return False
    return True


def infer_vision_support(model_id: str) -> bool:
    """Infer vision support from model ID when base model metadata unavailable.

    Used for cross-region inference profiles when the base model isn't
    available in the user's region.
    """
    model_id_lower = model_id.lower()
    return any(vision_model in model_id_lower for vision_model in BEDROCK_VISION_MODELS)


def generate_bedrock_display_name(model_id: str) -> str:
    """Generate a human-friendly display name for a Bedrock model ID.

    Examples:
        "anthropic.claude-3-5-sonnet-20241022-v2:0" → "Claude 3.5 Sonnet v2"
        "us.anthropic.claude-3-5-sonnet-..." → "Claude 3.5 Sonnet (us)"
        "meta.llama3-70b-instruct-v1:0" → "Llama 3 70B Instruct"
    """
    # Check for region prefix (us., eu., global., etc.)
    region = None
    if "." in model_id:
        parts = model_id.split(".", 1)
        if parts[0] in ("us", "eu", "global", "ap", "apac"):
            region = parts[0]
            model_id = parts[1]

    # Remove provider prefix (anthropic., meta., amazon., etc.)
    if "." in model_id:
        model_id = model_id.split(".", 1)[1]

    # Remove version suffix (:0, :1, etc.) and date stamps
    model_id = re.sub(r":\d+$", "", model_id)
    model_id = re.sub(r"-\d{8}-v\d+", "", model_id)  # -20241022-v2
    model_id = re.sub(r"-v\d+:\d+$", "", model_id)  # -v1:0
    model_id = re.sub(r"-v\d+$", "", model_id)  # -v1

    # Convert to display name
    display_name = model_id.replace("-", " ").replace("_", " ")

    # Apply proper casing for known models
    display_lower = display_name.lower()
    for key, proper_name in BEDROCK_MODEL_NAME_MAPPINGS.items():
        if key in display_lower:
            # Find and replace with proper casing
            pattern = re.compile(re.escape(key), re.IGNORECASE)
            display_name = pattern.sub(proper_name, display_name)
            break

    # Clean up version numbers (e.g., "3 5" -> "3.5")
    display_name = re.sub(r"(\d) (\d)", r"\1.\2", display_name)

    # Title case and clean up
    words = display_name.split()
    result_words = []
    for word in words:
        if word.lower() in BEDROCK_MODEL_NAME_MAPPINGS:
            result_words.append(BEDROCK_MODEL_NAME_MAPPINGS[word.lower()])
        elif word.isdigit() or re.match(r"^\d+[bBkKmM]?$", word):
            result_words.append(word.upper() if word[-1:].lower() in "bkm" else word)
        elif word.lower() in ("instruct", "chat", "pro", "lite", "mini", "premier"):
            result_words.append(word.title())
        else:
            result_words.append(word.title() if not word[0].isupper() else word)

    display_name = " ".join(result_words)

    # Add region suffix if present
    if region:
        display_name = f"{display_name} ({region})"

    return display_name


def generate_ollama_display_name(model_name: str) -> str:
    """Generate a human-friendly display name for an Ollama model.

    Examples:
        "llama3:latest" → "Llama 3"
        "llama3.3:70b" → "Llama 3.3 70B"
        "qwen2.5:7b" → "Qwen 2.5 7B"
        "mistral:latest" → "Mistral"
        "deepseek-r1:14b" → "DeepSeek R1 14B"
    """
    # Split into base name and tag
    if ":" in model_name:
        base, tag = model_name.rsplit(":", 1)
    else:
        base, tag = model_name, ""

    # Try to match known model families and apply proper casing
    display_name = base
    base_lower = base.lower()
    for key, proper_name in OLLAMA_MODEL_NAME_MAPPINGS.items():
        if base_lower.startswith(key):
            # Replace the matched part with proper casing, keep the rest
            suffix = base[len(key) :]
            # Handle version numbers like "3", "3.3", "2.5"
            if suffix and suffix[0].isdigit():
                suffix = " " + suffix
            # Handle dashes like "-r1", "-coder"
            elif suffix.startswith("-"):
                suffix = " " + suffix[1:].title()
            display_name = proper_name + suffix
            break
    else:
        # Default: Title case with dashes converted to spaces
        display_name = base.replace("-", " ").title()

    # Process tag to extract size info (skip "latest")
    if tag and tag.lower() != "latest":
        # Extract size like "7b", "70b", "14b"
        size_match = re.match(r"^(\d+(?:\.\d+)?[bBmM])", tag)
        if size_match:
            size = size_match.group(1).upper()
            display_name = f"{display_name} {size}"

    return display_name


def strip_openrouter_vendor_prefix(display_name: str, model_id: str) -> str:
    """Strip redundant vendor prefix from OpenRouter display names.

    OpenRouter returns names like "Microsoft: Phi 4" but we already group
    by vendor, so strip the prefix to avoid redundancy.

    Examples:
        ("Microsoft: Phi 4", "microsoft/phi-4") → "Phi 4"
        ("Mistral: Mixtral 8x7B Instruct", "mistralai/mixtral-8x7b") → "Mixtral 8x7B Instruct"
        ("Claude 3.5 Sonnet", "anthropic/claude-3.5-sonnet") → "Claude 3.5 Sonnet" (no prefix)
    """
    # Extract vendor from model ID (first part before "/")
    if "/" not in model_id:
        return display_name

    vendor_from_id = model_id.split("/")[0].lower()

    # Check if display name starts with "Vendor: " pattern
    if ": " in display_name:
        prefix, rest = display_name.split(": ", 1)
        # Normalize both for comparison (remove spaces, dashes, underscores)
        prefix_normalized = prefix.lower().replace(" ", "").replace("-", "")
        vendor_normalized = vendor_from_id.replace("-", "").replace("_", "")

        # Match if prefix matches vendor (handles "Mistral" vs "mistralai", etc.)
        if (
            prefix_normalized == vendor_normalized
            or prefix_normalized.startswith(vendor_normalized)
            or vendor_normalized.startswith(prefix_normalized)
        ):
            return rest

    return display_name


# Reasoning model patterns for OpenRouter
REASONING_MODEL_PATTERNS = frozenset(
    {
        "o1",
        "o3",
        "o4",
        "gpt-5",
        "thinking",
        "reason",
        "deepseek-r1",
        "qwq",
    }
)


def is_reasoning_model(model_id: str, display_name: str) -> bool:
    """Check if a model is a reasoning/thinking model based on its ID or name.

    Used for OpenRouter and other dynamic providers where we need to infer
    reasoning capability from model identifiers.
    """
    combined = f"{model_id} {display_name}".lower()
    return any(pattern in combined for pattern in REASONING_MODEL_PATTERNS)


def extract_base_model_name(model: str) -> str | None:
    """Extract base model name by removing date suffixes.

    Returns None if no date suffix was found.
    """
    patterns = [
        r"-\d{8}$",  # -20250929
        r"-\d{4}-\d{2}-\d{2}$",  # -2024-08-06
        r"@\d{8}$",  # @20250219
    ]
    for pattern in patterns:
        if re.search(pattern, model):
            return re.sub(pattern, "", model)
    return None


def should_filter_as_dated_duplicate(
    model_name: str, all_model_names: set[str]
) -> bool:
    """Check if this model is a dated variant and a non-dated version exists."""
    base = extract_base_model_name(model_name)
    if base and base in all_model_names:
        return True
    return False


def filter_model_configurations(
    model_configurations: list,
    provider: str,
) -> list:
    """Filter out obsolete and dated duplicate models from configurations.

    Args:
        model_configurations: List of ModelConfiguration DB models
        provider: The provider name (e.g., "openai", "anthropic")

    Returns:
        List of ModelConfigurationView objects with obsolete/duplicate models removed
    """
    # Import here to avoid circular imports
    from onyx.llm.well_known_providers.llm_provider_options import is_obsolete_model
    from onyx.server.manage.llm.models import ModelConfigurationView

    all_model_names = {mc.name for mc in model_configurations}

    filtered_configs = []
    for model_configuration in model_configurations:
        # Skip obsolete models
        if is_obsolete_model(model_configuration.name, provider):
            continue
        # Skip dated duplicates when non-dated version exists
        if should_filter_as_dated_duplicate(model_configuration.name, all_model_names):
            continue
        filtered_configs.append(
            ModelConfigurationView.from_model(model_configuration, provider)
        )

    return filtered_configs


def extract_vendor_from_model_name(model_name: str, provider: str) -> str | None:
    """Extract vendor from model name for aggregator providers.

    Examples:
        - OpenRouter: "anthropic/claude-3-5-sonnet" → "Anthropic"
        - Bedrock: "anthropic.claude-3-5-sonnet-..." → "Anthropic"
        - Bedrock: "us.anthropic.claude-..." → "Anthropic"
        - Ollama: "llama3:70b" → "Meta"
        - Ollama: "qwen2.5:7b" → "Alibaba"
    """
    if provider == LlmProviderNames.OPENROUTER:
        # Format: "vendor/model-name" e.g., "anthropic/claude-3-5-sonnet"
        if "/" in model_name:
            vendor_key = model_name.split("/")[0].lower()
            return PROVIDER_DISPLAY_NAMES.get(vendor_key, vendor_key.title())

    elif provider == LlmProviderNames.BEDROCK:
        # Format: "vendor.model-name" or "region.vendor.model-name"
        parts = model_name.split(".")
        if len(parts) >= 2:
            # Check if first part is a region (us, eu, global, etc.)
            if parts[0] in ("us", "eu", "global", "ap", "apac"):
                vendor_key = parts[1].lower() if len(parts) > 2 else parts[0].lower()
            else:
                vendor_key = parts[0].lower()
            return PROVIDER_DISPLAY_NAMES.get(vendor_key, vendor_key.title())

    elif provider == LlmProviderNames.OLLAMA_CHAT:
        # Format: "model-name:tag" e.g., "llama3:70b", "qwen2.5:7b"
        # Extract base name (before colon)
        base_name = model_name.split(":")[0].lower()
        # Match against known model prefixes
        for prefix, vendor in OLLAMA_MODEL_TO_VENDOR.items():
            if base_name.startswith(prefix):
                return vendor
        # Fallback: capitalize the base name as vendor
        return base_name.split("-")[0].title()

    return None
