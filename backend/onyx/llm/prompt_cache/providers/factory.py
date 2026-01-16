"""Factory for creating provider-specific prompt cache adapters."""

from onyx.llm.constants import LlmProviderNames
from onyx.llm.interfaces import LLMConfig
from onyx.llm.prompt_cache.providers.anthropic import AnthropicPromptCacheProvider
from onyx.llm.prompt_cache.providers.base import PromptCacheProvider
from onyx.llm.prompt_cache.providers.noop import NoOpPromptCacheProvider
from onyx.llm.prompt_cache.providers.openai import OpenAIPromptCacheProvider
from onyx.llm.prompt_cache.providers.vertex import VertexAIPromptCacheProvider

ANTHROPIC_BEDROCK_TAG = "anthropic."


def get_provider_adapter(llm_config: LLMConfig) -> PromptCacheProvider:
    """Get the appropriate prompt cache provider adapter for a given provider.

    Args:
        provider: Provider name (e.g., "openai", "anthropic", "vertex_ai")

    Returns:
        PromptCacheProvider instance for the given provider
    """
    if llm_config.model_provider == LlmProviderNames.OPENAI:
        return OpenAIPromptCacheProvider()
    elif llm_config.model_provider == LlmProviderNames.ANTHROPIC or (
        llm_config.model_provider == LlmProviderNames.BEDROCK
        and ANTHROPIC_BEDROCK_TAG in llm_config.model_name
    ):
        return AnthropicPromptCacheProvider()
    elif llm_config.model_provider == LlmProviderNames.VERTEX_AI:
        return VertexAIPromptCacheProvider()
    else:
        # Default to no-op for providers without caching support
        return NoOpPromptCacheProvider()
