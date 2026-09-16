"""Base interface for provider-specific prompt caching adapters."""

from abc import ABC, abstractmethod

from onyx.llm.interfaces import LanguageModelInput
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
        cacheable_prefix: LanguageModelInput | None,
        suffix: LanguageModelInput,
        continuation: bool,
        cache_metadata: CacheMetadata | None,
    ) -> LanguageModelInput:
        """Transform messages to enable caching.

        Args:
            cacheable_prefix: Optional cacheable prefix (can be str or Sequence[ChatCompletionMessage])
            suffix: Non-cacheable suffix (can be str or Sequence[ChatCompletionMessage])
            continuation: If True, suffix should be appended to the last message
                of cacheable_prefix rather than being separate messages.
                Note: When cacheable_prefix is a string, it should remain in its own
                content block even if continuation=True.
            cache_metadata: Optional cache metadata from previous requests

        Returns:
            Combined and transformed messages ready for LLM API call
        """
        raise NotImplementedError
