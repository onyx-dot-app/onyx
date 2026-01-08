"""Main processor for prompt caching."""

from datetime import datetime
from datetime import timezone

from onyx.configs.model_configs import ENABLE_PROMPT_CACHING
from onyx.llm.interfaces import LLMConfig
from onyx.llm.models import LanguageModelInput
from onyx.llm.prompt_cache.cache_manager import generate_cache_key_hash
from onyx.llm.prompt_cache.models import CacheMetadata
from onyx.llm.prompt_cache.providers.factory import get_provider_adapter
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()


# TODO: test with a history containing images
def process_with_prompt_cache(
    llm_config: LLMConfig,
    cacheable_prefix: LanguageModelInput | None,
    suffix: LanguageModelInput,
    continuation: bool = False,
) -> tuple[LanguageModelInput, CacheMetadata | None]:
    """Process prompt with caching support.

    This function takes a cacheable prefix and suffix, processes them according to
    the LLM provider's caching capabilities, and returns the combined messages
    ready for LLM API calls along with optional cache metadata.

    Args:
        llm: The LLM instance (used to determine provider and model)
        cacheable_prefix: Optional cacheable prefix. If None, no caching is attempted.
        suffix: The non-cacheable suffix to append
        continuation: If True, suffix should be appended to the last message
            of cacheable_prefix rather than being separate messages

    Returns:
        Tuple of (processed_prompt, cache_metadata_to_store)
        - processed_prompt: Combined and transformed messages ready for LLM API call
        - cache_metadata_to_store: Optional cache metadata for post-processing
            (currently None for implicit caching, will be populated in future PR
            for explicit caching)
    """
    # Check if prompt caching is enabled
    if not ENABLE_PROMPT_CACHING:
        logger.debug("Prompt caching is disabled via configuration")
        # Fall back to no-op behavior
        from onyx.llm.prompt_cache.providers.noop import NoOpPromptCacheProvider

        noop_adapter = NoOpPromptCacheProvider()
        combined = noop_adapter.prepare_messages_for_caching(
            cacheable_prefix=cacheable_prefix,
            suffix=suffix,
            continuation=continuation,
            cache_metadata=None,
        )
        return combined, None

    # If no cacheable prefix, return suffix unchanged
    if cacheable_prefix is None:
        logger.debug("No cacheable prefix provided, skipping caching")
        return suffix, None

    # Get provider adapter
    provider_adapter = get_provider_adapter(llm_config.model_provider)

    # If provider doesn't support caching, combine and return unchanged
    if not provider_adapter.supports_caching():
        logger.debug(
            f"Provider {llm_config.model_provider} does not support caching, "
            "combining messages without caching"
        )
        # Use no-op adapter to combine messages
        from onyx.llm.prompt_cache.providers.noop import NoOpPromptCacheProvider

        noop_adapter = NoOpPromptCacheProvider()
        combined = noop_adapter.prepare_messages_for_caching(
            cacheable_prefix=cacheable_prefix,
            suffix=suffix,
            continuation=continuation,
            cache_metadata=None,
        )
        return combined, None

    # Generate cache key for cacheable prefix
    tenant_id = get_current_tenant_id()
    cache_key_hash = generate_cache_key_hash(
        cacheable_prefix=cacheable_prefix,
        provider=llm_config.model_provider,
        model_name=llm_config.model_name,
        tenant_id=tenant_id,
    )

    # For implicit caching: Skip cache lookup (providers handle caching automatically)
    # TODO (explicit caching - future PR): Look up cache metadata in CacheManager
    cache_metadata: CacheMetadata | None = None

    # Use provider adapter to prepare messages with caching
    try:
        processed_prompt = provider_adapter.prepare_messages_for_caching(
            cacheable_prefix=cacheable_prefix,
            suffix=suffix,
            continuation=continuation,
            cache_metadata=cache_metadata,
        )

        logger.debug(
            f"Processed prompt with caching: provider={llm_config.model_provider}, "
            f"model={llm_config.model_name}, cache_key={cache_key_hash[:16]}..., "
            f"continuation={continuation}"
        )

        # Create cache metadata for tracking (even for implicit caching)
        # This allows us to track cache usage and effectiveness
        cache_metadata = CacheMetadata(
            cache_key=cache_key_hash,
            provider=llm_config.model_provider,
            model_name=llm_config.model_name,
            tenant_id=tenant_id,
            created_at=datetime.now(timezone.utc),
            last_accessed=datetime.now(timezone.utc),
        )

        return processed_prompt, cache_metadata

    except Exception as e:
        # Best-effort: log error and fall back to no-op behavior
        logger.warning(
            f"Error processing prompt with caching for provider={llm_config.model_provider}: {str(e)}. "
            "Falling back to non-cached behavior."
        )
        # Fall back to no-op adapter
        from onyx.llm.prompt_cache.providers.noop import NoOpPromptCacheProvider

        noop_adapter = NoOpPromptCacheProvider()
        combined = noop_adapter.prepare_messages_for_caching(
            cacheable_prefix=cacheable_prefix,
            suffix=suffix,
            continuation=continuation,
            cache_metadata=None,
        )
        return combined, None
