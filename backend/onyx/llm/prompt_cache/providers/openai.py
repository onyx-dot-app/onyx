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
        cache_metadata: CacheMetadata | None,  # noqa: ARG002
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
