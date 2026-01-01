"""
Unit tests for LiteLLM model name parser.

Tests verify that enrichment data is correctly returned from the parser.
"""

from onyx.llm.constants import LlmProviderNames
from onyx.llm.model_name_parser import parse_litellm_model_name


def test_bedrock_model_with_enrichment() -> None:
    """Test parsing a Bedrock model - provider extracted, metadata from enrichment."""
    result = parse_litellm_model_name(
        "bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0"
    )

    assert result.raw_name == "bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0"
    assert result.provider == LlmProviderNames.BEDROCK
    assert result.vendor == LlmProviderNames.ANTHROPIC
    assert result.display_name == "Claude Sonnet 3.5"
    assert result.provider_display_name == "Claude (Bedrock - Anthropic)"


def test_region_extraction() -> None:
    """Test that region prefix is extracted from model key."""
    result = parse_litellm_model_name(
        "bedrock/eu.anthropic.claude-3-5-sonnet-20241022-v2:0"
    )

    assert result.region == "eu"
    assert result.provider == LlmProviderNames.BEDROCK


def test_direct_provider_inference() -> None:
    """Test that provider is inferred from litellm.model_cost for unprefixed models."""
    result = parse_litellm_model_name("gpt-4o")

    assert result.provider == LlmProviderNames.OPENAI
    assert result.display_name == "GPT-4o"
    assert result.provider_display_name == "GPT (OpenAI)"


def test_unknown_model_fallback() -> None:
    """Test that unknown models get a cleaned-up display name."""
    result = parse_litellm_model_name("some-unknown-model-xyz")

    assert result.raw_name == "some-unknown-model-xyz"
    # Unknown models get title-cased display names
    assert result.display_name == "Some Unknown Model Xyz"
    assert result.vendor is None
