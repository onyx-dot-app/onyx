"""No-op provider adapter for providers without caching support."""

from onyx.llm.model_request import ChatCompletionMessage
from onyx.llm.prompt_cache.models import CacheMetadata
from onyx.llm.prompt_cache.providers.base import PromptCacheProvider
from onyx.llm.prompt_cache.utils import prepare_messages_with_cacheable_transform


class NoOpPromptCacheProvider(PromptCacheProvider):
    """No-op adapter for providers that don't support prompt caching."""

    def supports_caching(self) -> bool:
        """No-op providers don't support caching."""
        return False

    def prepare_messages_for_caching(
        self,
        cacheable_prefix: list[ChatCompletionMessage] | None,
        suffix: list[ChatCompletionMessage],
        continuation: bool,
        cache_metadata: CacheMetadata | None,  # noqa: ARG002
    ) -> list[ChatCompletionMessage]:
        """Return messages unchanged (no caching support).

        Args:
            cacheable_prefix: Optional cacheable prefix as a message list
            suffix: Non-cacheable suffix as a message list
            continuation: Whether to append suffix to last prefix message.
                Note: When cacheable_prefix is a string, it remains in its own content block.
            cache_metadata: Cache metadata (ignored)

        Returns:
            Combined messages (prefix + suffix)
        """
        # No transformation needed for no-op provider
        return prepare_messages_with_cacheable_transform(
            cacheable_prefix=cacheable_prefix,
            suffix=suffix,
            continuation=continuation,
            transform_cacheable=None,
        )

    def extract_cache_metadata(
        self,
        response: dict,  # noqa: ARG002
        cache_key: str,  # noqa: ARG002
    ) -> CacheMetadata | None:
        """No cache metadata to extract."""
        return None

    def get_cache_ttl_seconds(self) -> int:
        """Return default TTL (not used for no-op)."""
        return 0
