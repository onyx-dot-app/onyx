"""Vertex AI provider adapter for prompt caching."""

from onyx.llm.interfaces import LanguageModelInput
from onyx.llm.prompt_cache.models import CacheMetadata
from onyx.llm.prompt_cache.providers.base import PromptCacheProvider
from onyx.llm.prompt_cache.utils import (
    prepare_messages_with_cacheable_transform,
)


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
        cache_metadata: CacheMetadata | None,  # noqa: ARG002
    ) -> LanguageModelInput:
        """Prepare messages for Vertex AI caching.

        For implicit caching we attach cache_control={"type": "ephemeral"} to every
        cacheable prefix message so Vertex/Gemini can reuse them automatically.
        Explicit context caching (with cache blocks) will be added in a future PR.

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
            transform_cacheable=None,  # TODO: support explicit caching
        )
