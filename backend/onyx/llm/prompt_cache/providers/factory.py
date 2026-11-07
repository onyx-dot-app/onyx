"""Factory for creating provider-specific prompt cache adapters."""

import logging
import re

from onyx.llm.api_surfaces import LlmApiSurface, resolve_api_surface
from onyx.llm.constants import AGGREGATOR_PROVIDERS, LlmProviderNames
from onyx.llm.interfaces import LLMConfig
from onyx.llm.prompt_cache.providers.anthropic import AnthropicPromptCacheProvider
from onyx.llm.prompt_cache.providers.base import PromptCacheProvider
from onyx.llm.prompt_cache.providers.noop import NoOpPromptCacheProvider
from onyx.llm.prompt_cache.providers.openai import OpenAIPromptCacheProvider
from onyx.llm.prompt_cache.providers.vertex import VertexAIPromptCacheProvider

logger = logging.getLogger(__name__)

# OpenRouter model name prefixes — used to determine which upstream provider
# is being called so the correct caching strategy can be applied.
OPENROUTER_ANTHROPIC_PREFIX = "anthropic/"
OPENROUTER_GOOGLE_PREFIX = "google/"
OPENROUTER_OPENAI_PREFIX = "openai/"


def _adapter_for_aggregator(llm_config: LLMConfig) -> PromptCacheProvider:
    """Pick a cache adapter for an aggregator/gateway by surface + model name.

    Gateways forward message-level ``cache_control`` to Anthropic upstreams
    (LiteLLM, Bifrost, and Portkey all translate it on their chat-completions
    surface). Non-Anthropic upstreams rely on implicit caching, which needs no
    message mutation, so they fall through to no-op.
    """
    if (
        resolve_api_surface(llm_config.model_provider, llm_config.custom_config)
        == LlmApiSurface.ANTHROPIC_MESSAGES
    ):
        return AnthropicPromptCacheProvider()
    # Match on name segments only ("anthropic/claude-sonnet", "claude-sonnet-4-5"),
    # so an unrelated deployment that merely contains the substring
    # ("claudio-fast", "myanthropic-proxy") is not misclassified.
    model_name: str = (llm_config.model_name or "").lower()
    segments: frozenset[str] = frozenset(re.split(r"[/._\-\s]+", model_name))
    if "anthropic" in segments or "claude" in segments:
        logger.debug(
            "Prompt caching enabled for gateway Anthropic model: %s (provider=%s)",
            llm_config.model_name,
            llm_config.model_provider,
        )
        return AnthropicPromptCacheProvider()
    logger.debug(
        "Prompt caching not supported for gateway model: %s (provider=%s)",
        llm_config.model_name,
        llm_config.model_provider,
    )
    return NoOpPromptCacheProvider()


def _adapter_for_bedrock(llm_config: LLMConfig) -> PromptCacheProvider:
    """Pick a cache adapter for a Bedrock model by declared cache support.

    LiteLLM translates ``cache_control`` into Converse ``cachePoint`` blocks on
    system, user, and tool messages, so the Anthropic-style marker works for
    any cache-capable Bedrock model (Claude, Amazon Nova). Models that
    litellm's model map does not mark cache-capable get no-op: a ``cachePoint``
    sent to a non-capable model fails the Converse call.
    """
    import litellm.utils

    names: list[str] = [
        name for name in (llm_config.deployment_name, llm_config.model_name) if name
    ]
    cacheable: bool = False
    for name in names:
        try:
            if litellm.utils.supports_prompt_caching(
                model=name, custom_llm_provider="bedrock"
            ):
                cacheable = True
                break
        except ValueError:
            # Absent from the model-cost map — treated as not cache-capable.
            continue
        except Exception as e:
            logger.warning(
                "Prompt-caching capability lookup failed for Bedrock model: %s — %s",
                name,
                e,
            )
    if cacheable:
        logger.debug(
            "Prompt caching enabled for Bedrock model: %s (provider=%s)",
            llm_config.model_name,
            llm_config.model_provider,
        )
        return AnthropicPromptCacheProvider()
    logger.debug(
        "Prompt caching not supported for Bedrock model: %s (provider=%s)",
        llm_config.model_name,
        llm_config.model_provider,
    )
    return NoOpPromptCacheProvider()


def get_provider_adapter(llm_config: LLMConfig) -> PromptCacheProvider:
    """Get the appropriate prompt cache provider adapter for a given provider.

    Args:
        llm_config: Config of the LLM whose provider decides the caching strategy

    Returns:
        PromptCacheProvider instance for the given provider
    """
    if llm_config.model_provider == LlmProviderNames.OPENAI:
        return OpenAIPromptCacheProvider()
    elif llm_config.model_provider == LlmProviderNames.ANTHROPIC:
        return AnthropicPromptCacheProvider()
    elif llm_config.model_provider in (
        LlmProviderNames.BEDROCK,
        LlmProviderNames.BEDROCK_CONVERSE,
    ):
        # Capability-checked before the aggregator fallback so cacheable
        # non-Claude models (Amazon Nova) are covered and non-cacheable
        # models are not over-marked.
        return _adapter_for_bedrock(llm_config)
    elif llm_config.model_provider == LlmProviderNames.VERTEX_AI:
        return VertexAIPromptCacheProvider()
    elif llm_config.model_provider == LlmProviderNames.OPENROUTER:
        model_name = llm_config.model_name or ""
        if model_name.startswith(OPENROUTER_ANTHROPIC_PREFIX):
            logger.debug(
                "Prompt caching enabled for OpenRouter Anthropic model: %s", model_name
            )
            return AnthropicPromptCacheProvider()
        elif model_name.startswith(OPENROUTER_GOOGLE_PREFIX):
            logger.debug(
                "Prompt caching enabled for OpenRouter Google/Gemini model: %s",
                model_name,
            )
            # NOTE: Reusing VertexAIPromptCacheProvider is safe today because it
            # only does implicit caching (no message mutation). These requests go
            # through OpenRouter, not the Vertex SDK.
            # TODO: once Vertex explicit caching (context-cache block IDs) lands,
            # split this out into a dedicated OpenRouter Google provider so the
            # Vertex-specific behavior doesn't leak into OpenRouter requests.
            return VertexAIPromptCacheProvider()
        elif model_name.startswith(OPENROUTER_OPENAI_PREFIX):
            logger.debug(
                "Prompt caching enabled for OpenRouter OpenAI model: %s", model_name
            )
            return OpenAIPromptCacheProvider()
        else:
            logger.debug(
                "Prompt caching not supported for OpenRouter model: %s", model_name
            )
            return NoOpPromptCacheProvider()
    elif llm_config.model_provider in AGGREGATOR_PROVIDERS:
        # Aggregators/gateways can serve any upstream model, so the adapter is
        # picked from the API surface and the model name. Providers with their
        # own handling (openrouter, bedrock, vertex) are matched above and
        # never reach this branch.
        return _adapter_for_aggregator(llm_config)
    else:
        # Default to no-op for providers without caching support
        return NoOpPromptCacheProvider()
