"""Vertex AI provider adapter for prompt caching."""

from onyx.llm.interfaces import LanguageModelInput
from onyx.llm.prompt_cache.interfaces import CacheMetadata
from onyx.llm.prompt_cache.providers.base import PromptCacheProvider
from onyx.llm.prompt_cache.utils import prepare_messages_with_cacheable_transform


class VertexAIPromptCacheProvider(PromptCacheProvider):
    """Vertex AI adapter for prompt caching (implicit caching for this PR)."""

    def supports_caching(self) -> bool:
        """Vertex AI supports prompt caching (implicit and explicit)."""
        return True

    def prepare_messages_for_caching(
        self,
        cacheable_prefix: LanguageModelInput | None,
        suffix: LanguageModelInput,
        continuation: bool,
        cache_metadata: CacheMetadata | None,
    ) -> LanguageModelInput:
        """Prepare messages for Vertex AI caching.

        For this PR, we only implement implicit caching (automatic, similar to OpenAI).
        Vertex handles implicit caching automatically, so we just normalize and combine.

        TODO (explicit caching - future PR):
        - If cache_metadata exists and has vertex_block_numbers: Replace message content
          with {"cache_block_id": "<block_number>"}
        - If not: Add cache_control={"type": "ephemeral"} to cacheable messages

        Args:
            cacheable_prefix: Optional cacheable prefix
            suffix: Non-cacheable suffix
            continuation: Whether to append suffix to last prefix message
            cache_metadata: Cache metadata (for future explicit caching support)

        Returns:
            Combined messages ready for LLM API call
        """
        # For implicit caching, no transformation needed (Vertex handles caching automatically)
        # TODO (explicit caching - future PR):
        # - Check cache_metadata for vertex_block_numbers
        # - Create transform function that replaces messages with cache_block_id if available
        # - Or adds cache_control parameter if not using cached blocks
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
        """Extract cache metadata from Vertex AI response.

        For this PR (implicit caching): Extract basic cache usage info if available.
        TODO (explicit caching - future PR): Extract block numbers from response
        and store in metadata.

        Args:
            response: Vertex AI API response dictionary
            cache_key: Cache key used for this request

        Returns:
            CacheMetadata if extractable, None otherwise
        """
        # For implicit caching, Vertex handles everything automatically
        # TODO (explicit caching - future PR):
        # - Extract cache block numbers from response
        # - Store in cache_metadata.vertex_block_numbers
        return None

    def get_cache_ttl_seconds(self) -> int:
        """Get cache TTL for Vertex AI (5 minutes)."""
        return 300
