"""OpenAI provider adapter for prompt caching."""

from onyx.llm.interfaces import LanguageModelInput
from onyx.llm.prompt_cache.models import CacheMetadata
from onyx.llm.prompt_cache.providers.base import PromptCacheProvider
from onyx.llm.prompt_cache.utils import prepare_messages_with_cacheable_transform


class OpenAIPromptCacheProvider(PromptCacheProvider):
    """OpenAI adapter for prompt caching (implicit caching)."""

    def supports_caching(self) -> bool:
        """OpenAI supports automatic prompt caching."""
        return True

    def prepare_messages_for_caching(
        self,
        cacheable_prefix: LanguageModelInput | None,
        suffix: LanguageModelInput,
        continuation: bool,
        cache_metadata: CacheMetadata | None,
    ) -> LanguageModelInput:
        """Prepare messages for OpenAI caching.

        OpenAI handles caching automatically, so we just normalize and combine
        the messages. The provider will automatically cache prefixes >1024 tokens.

        Args:
            cacheable_prefix: Optional cacheable prefix
            suffix: Non-cacheable suffix
            continuation: Whether to append suffix to last prefix message
            cache_metadata: Cache metadata (ignored for implicit caching)

        Returns:
            Combined messages ready for LLM API call
        """
        # No transformation needed for OpenAI (implicit caching)
        return prepare_messages_with_cacheable_transform(
            cacheable_prefix=cacheable_prefix,
            suffix=suffix,
            continuation=continuation,
            transform_cacheable=None,
        )

    def extract_cache_metadata(
        self,
        response: dict,
        cache_key: str,
    ) -> CacheMetadata | None:
        """Extract cache metadata from OpenAI response.

        OpenAI responses may include cached_tokens in the usage field.
        For implicit caching, we don't need to store much metadata.

        Args:
            response: OpenAI API response dictionary
            cache_key: Cache key used for this request

        Returns:
            CacheMetadata if extractable, None otherwise
        """
        # For implicit caching, OpenAI handles everything automatically
        # We could extract cached_tokens from response.get("usage", {}).get("cached_tokens")
        # but for now, we don't need to store metadata for implicit caching
        return None

    def get_cache_ttl_seconds(self) -> int:
        """Get cache TTL for OpenAI (1 hour max)."""
        return 3600
