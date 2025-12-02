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

from functools import lru_cache

from pydantic import BaseModel

from onyx.llm.constants import AGGREGATOR_PROVIDERS
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
        if litellm_provider.startswith("vertex_ai"):
            return "vertex_ai"
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

    All metadata comes from enrichment - no inference or fallback logic.

    Args:
        raw_name: The LiteLLM model string

    Returns:
        ParsedModelName with all components from enrichment
    """
    model_info = _get_model_info(raw_name)

    # Extract from key (not in enrichment)
    provider = _extract_provider(raw_name)
    region = _extract_region(raw_name)

    # Get from enrichment
    vendor = model_info.get("model_vendor")
    version = model_info.get("model_version")
    display_name = model_info.get("display_name", raw_name)

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
