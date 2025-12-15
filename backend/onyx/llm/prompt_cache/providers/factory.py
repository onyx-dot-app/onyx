"""Factory for creating provider-specific prompt cache adapters."""

from onyx.llm.llm_provider_options import ANTHROPIC_PROVIDER_NAME
from onyx.llm.llm_provider_options import OPENAI_PROVIDER_NAME
from onyx.llm.llm_provider_options import VERTEXAI_PROVIDER_NAME
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
    if provider == OPENAI_PROVIDER_NAME:
        return OpenAIPromptCacheProvider()
    elif provider == ANTHROPIC_PROVIDER_NAME:
        return AnthropicPromptCacheProvider()
    elif provider == VERTEXAI_PROVIDER_NAME:
        return VertexAIPromptCacheProvider()
    else:
        # Default to no-op for providers without caching support
        return NoOpPromptCacheProvider()
