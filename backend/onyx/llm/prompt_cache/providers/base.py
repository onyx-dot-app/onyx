"""Base interface for provider-specific prompt caching adapters."""

from abc import ABC, abstractmethod

from onyx.llm.litellm_models import ChatCompletionMessage
from onyx.llm.prompt_cache.models import CacheMetadata


class PromptCacheProvider(ABC):
    """Abstract base class for provider-specific prompt caching logic."""

    @abstractmethod
    def supports_caching(self) -> bool:
        """Whether this provider supports prompt caching.

        Returns:
            True if caching is supported, False otherwise
        """
        raise NotImplementedError

    @abstractmethod
    def prepare_messages_for_caching(
        self,
        cacheable_prefix: list[ChatCompletionMessage] | None,
        suffix: list[ChatCompletionMessage],
        continuation: bool,
        cache_metadata: CacheMetadata | None,
    ) -> list[ChatCompletionMessage]:
        """Transform messages to enable caching.

        Args:
            cacheable_prefix: Optional cacheable prefix as a message list
            suffix: Non-cacheable suffix as a message list
            continuation: If True, suffix should be appended to the last message
                of cacheable_prefix rather than being separate messages.
                Note: When cacheable_prefix is a string, it should remain in its own
                content block even if continuation=True.
            cache_metadata: Optional cache metadata from previous requests

        Returns:
            Combined and transformed messages ready for LLM API call
        """
        raise NotImplementedError

    @abstractmethod
    def extract_cache_metadata(
        self,
        response: dict,  # Provider-specific response object
        cache_key: str,
    ) -> CacheMetadata | None:
        """Extract cache metadata from API response.

        Args:
            response: Provider-specific response dictionary
            cache_key: Cache key used for this request

        Returns:
            CacheMetadata if extractable, None otherwise
        """
        raise NotImplementedError

    @abstractmethod
    def get_cache_ttl_seconds(self) -> int:
        """Get cache TTL in seconds for this provider.

        Returns:
            TTL in seconds
        """
        raise NotImplementedError
