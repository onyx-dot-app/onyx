"""
LiteLLM Model Name Parser

Parses LiteLLM model strings and returns structured metadata for UI display.
All metadata comes from litellm's model_cost dictionary. Until this upstream patch to LiteLLM
is merged (https://github.com/BerriAI/litellm/pull/17330), we use the model_metadata_enrichments.json
to add these fields at server startup.

Enrichment fields:
- display_name: Human-friendly name (e.g., "Claude 3.5 Sonnet")
- model_vendor: The company that made the model (anthropic, openai, meta, etc.)
- model_version: Version string (e.g., "20241022-v2:0", "v1:0")

The parser only extracts provider and region from the model key - everything
else comes from enrichment.
"""

import re
from functools import lru_cache

from pydantic import BaseModel

from onyx.llm.constants import AGGREGATOR_PROVIDERS
from onyx.llm.constants import HYPHENATED_MODEL_NAMES
from onyx.llm.constants import LlmProviderNames
from onyx.llm.constants import MODEL_PREFIX_TO_VENDOR
from onyx.llm.constants import PROVIDER_DISPLAY_NAMES
from onyx.llm.constants import VENDOR_BRAND_NAMES


class ParsedModelName(BaseModel):
    """Structured representation of a parsed LiteLLM model name."""

    raw_name: str  # Original: "bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0"
    provider: str  # "bedrock", "azure", "openai", etc. (the API route)
    vendor: str | None = None  # From enrichment: "anthropic", "openai", "meta", etc.
    version: str | None = None  # From enrichment: "20241022-v2:0", "v1:0", etc.
    region: str | None = None  # Extracted: "us", "eu", or None
    display_name: str  # From enrichment: "Claude 3.5 Sonnet"
    provider_display_name: str  # Generated: "Claude (Bedrock - Anthropic)"


def _get_model_info(model_key: str) -> dict:
    """Get model info from litellm.model_cost."""
    from onyx.llm.litellm_singleton import litellm

    # Try exact key first
    info = litellm.model_cost.get(model_key)
    if info:
        return info

    # Try without provider prefix (e.g., "bedrock/anthropic.claude-..." -> "anthropic.claude-...")
    if "/" in model_key:
        return litellm.model_cost.get(model_key.split("/", 1)[-1], {})

    return {}


def _extract_provider(model_key: str) -> str:
    """Extract provider from model key prefix."""
    from onyx.llm.litellm_singleton import litellm

    if "/" in model_key:
        return model_key.split("/")[0]

    # No prefix - try to get from litellm.model_cost
    info = litellm.model_cost.get(model_key, {})
    litellm_provider = info.get("litellm_provider", "")

    if litellm_provider:
        # Normalize vertex_ai variants
        if litellm_provider.startswith(LlmProviderNames.VERTEX_AI):
            return LlmProviderNames.VERTEX_AI
        return litellm_provider

    return "unknown"


def _extract_region(model_key: str) -> str | None:
    """Extract region from model key (e.g., us., eu., apac. prefix)."""
    base = model_key.split("/")[-1].lower()

    for prefix in ["us.", "eu.", "apac.", "global.", "us-gov."]:
        if base.startswith(prefix):
            return prefix.rstrip(".")

    return None


def _format_name(name: str | None) -> str:
    """Format provider or vendor name with proper capitalization."""
    if not name:
        return "Unknown"
    return PROVIDER_DISPLAY_NAMES.get(name.lower(), name.replace("_", " ").title())


def _infer_vendor_from_model_name(model_name: str) -> str | None:
    """
    Infer vendor from model name patterns when enrichment data is missing.

    Uses MODEL_PREFIX_TO_VENDOR mapping to match model name prefixes.
    Returns lowercase vendor name for consistency with enrichment data.

    Examples:
        "gemini-3-flash-preview" → "google"
        "claude-3-5-sonnet" → "anthropic"
        "llama-3.1-70b" → "meta"
    """
    try:
        # Get the base model name (remove provider prefix if present)
        base_name = model_name.split("/")[-1].lower()

        # Try to match against known prefixes (sorted by length to match longest first)
        for prefix in sorted(MODEL_PREFIX_TO_VENDOR.keys(), key=len, reverse=True):
            if base_name.startswith(prefix):
                return MODEL_PREFIX_TO_VENDOR[prefix]
    except Exception:
        pass

    return None


def _generate_display_name_from_model(model_name: str) -> str:
    """
    Generate a human-friendly display name from a model identifier.

    Used as fallback when the model is not in enrichment data.
    Cleans up the raw model name by removing provider prefixes and
    formatting version numbers nicely.

    Examples:
        "vertex_ai/gemini-3-flash-preview" → "Gemini 3 Flash Preview"
        "gemini-2.5-pro-exp-03-25" → "Gemini 2.5 Pro"
        "claude-3-5-sonnet-20241022" → "Claude 3.5 Sonnet"
        "gpt-oss:120b" → "GPT-OSS 120B" (hyphenated exception)
    """
    try:
        # Remove provider prefix if present
        base_name = model_name.split("/")[-1]

        # Remove tag suffix (e.g., :14b, :latest) - handle separately
        size_suffix = ""
        if ":" in base_name:
            base_name, tag = base_name.rsplit(":", 1)
            # Keep size tags like "14b", "70b", "120b"
            if re.match(r"^\d+[bBmM]$", tag):
                size_suffix = f" {tag.upper()}"

        # Check if this is a hyphenated model that should keep its format
        base_name_lower = base_name.lower()
        for hyphenated in HYPHENATED_MODEL_NAMES:
            if base_name_lower.startswith(hyphenated):
                # Keep the hyphenated prefix, uppercase it
                return hyphenated.upper() + size_suffix

        # Remove common suffixes: date stamps, version numbers
        cleaned = base_name
        # Remove date stamps like -20241022, @20250219, -2024-08-06
        cleaned = re.sub(r"[-@]\d{4}-?\d{2}-?\d{2}", "", cleaned)
        # Remove experimental/preview date suffixes like -exp-03-25
        cleaned = re.sub(r"-exp-\d{2}-\d{2}", "", cleaned)
        # Remove version suffixes like -v1, -v2
        cleaned = re.sub(r"-v\d+$", "", cleaned)

        # Convert separators to spaces
        cleaned = cleaned.replace("-", " ").replace("_", " ")

        # Clean up version numbers: "3 5" → "3.5", "2 5" → "2.5"
        # But only for single digits that look like version numbers
        cleaned = re.sub(r"(\d) (\d)(?!\d)", r"\1.\2", cleaned)

        # Title case each word, preserving version numbers
        words = cleaned.split()
        result_words = []
        for word in words:
            if word.isdigit() or re.match(r"^\d+\.?\d*$", word):
                # Keep numbers as-is
                result_words.append(word)
            elif word.lower() in ("pro", "lite", "mini", "flash", "preview", "ultra"):
                # Common suffixes get title case
                result_words.append(word.title())
            else:
                # Title case other words
                result_words.append(word.title())

        return " ".join(result_words) + size_suffix
    except Exception:
        return model_name


def _generate_provider_display_name(provider: str, vendor: str | None) -> str:
    """
    Generate provider display name with model brand and vendor info.

    Examples:
        - Direct OpenAI: "GPT (OpenAI)"
        - Bedrock via Anthropic: "Claude (Bedrock - Anthropic)"
        - Vertex AI via Google: "Gemini (Vertex AI - Google)"
    """
    provider_nice = _format_name(provider)
    vendor_nice = _format_name(vendor) if vendor else None
    brand = VENDOR_BRAND_NAMES.get(vendor.lower()) if vendor else None

    # For aggregator providers, show: Brand (Provider - Vendor)
    if provider.lower() in AGGREGATOR_PROVIDERS:
        if brand and vendor_nice:
            return f"{brand} ({provider_nice} - {vendor_nice})"
        elif vendor_nice:
            return f"{provider_nice} - {vendor_nice}"
        return provider_nice

    # For direct providers, show: Brand (Provider)
    if brand:
        return f"{brand} ({provider_nice})"

    return provider_nice


@lru_cache(maxsize=1024)
def parse_litellm_model_name(raw_name: str) -> ParsedModelName:
    """
    Parse a LiteLLM model string into structured data.

    Metadata comes from enrichment when available, with fallback logic
    for models not in the enrichment data.

    Args:
        raw_name: The LiteLLM model string

    Returns:
        ParsedModelName with all components from enrichment or fallback
    """
    model_info = _get_model_info(raw_name)

    # Extract from key (not in enrichment)
    provider = _extract_provider(raw_name)
    region = _extract_region(raw_name)

    # Get from enrichment, with fallbacks for unenriched models
    vendor = model_info.get("model_vendor") or _infer_vendor_from_model_name(raw_name)
    version = model_info.get("model_version")
    display_name = model_info.get("display_name") or _generate_display_name_from_model(
        raw_name
    )

    # Generate provider display name
    provider_display_name = _generate_provider_display_name(provider, vendor)

    return ParsedModelName(
        raw_name=raw_name,
        provider=provider,
        vendor=vendor,
        version=version,
        region=region,
        display_name=display_name,
        provider_display_name=provider_display_name,
    )
