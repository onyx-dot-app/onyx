"""Factory for creating provider-specific prompt cache adapters."""

from onyx.llm.constants import LlmProviderNames
from onyx.llm.prompt_cache.providers.anthropic import AnthropicPromptCacheProvider
from onyx.llm.prompt_cache.providers.base import PromptCacheProvider
from onyx.llm.prompt_cache.providers.noop import NoOpPromptCacheProvider
from onyx.llm.prompt_cache.providers.openai import OpenAIPromptCacheProvider
from onyx.llm.prompt_cache.providers.vertex import VertexAIPromptCacheProvider


def get_provider_adapter(provider: str) -> PromptCacheProvider:
    """Get the appropriate prompt cache provider adapter for a given provider.

    Args:
        provider: Provider name (e.g., "openai", "anthropic", "vertex_ai")

    Returns:
        PromptCacheProvider instance for the given provider
    """
    if provider == LlmProviderNames.OPENAI:
        return OpenAIPromptCacheProvider()
    elif provider in [LlmProviderNames.ANTHROPIC, LlmProviderNames.BEDROCK]:
        return AnthropicPromptCacheProvider()
    elif provider == LlmProviderNames.VERTEX_AI:
        return VertexAIPromptCacheProvider()
    else:
        # Default to no-op for providers without caching support
        return NoOpPromptCacheProvider()
