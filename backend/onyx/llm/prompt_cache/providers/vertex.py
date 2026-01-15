"""Vertex AI provider adapter for prompt caching."""

from collections.abc import Sequence

from onyx.llm.interfaces import LanguageModelInput
from onyx.llm.models import ChatCompletionMessage
from onyx.llm.prompt_cache.models import CacheMetadata
from onyx.llm.prompt_cache.providers.base import PromptCacheProvider
from onyx.llm.prompt_cache.utils import prepare_messages_with_cacheable_transform
from onyx.llm.prompt_cache.utils import revalidate_message_from_original


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
            transform_cacheable=_add_vertex_cache_control,
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


def _add_vertex_cache_control(
    messages: Sequence[ChatCompletionMessage],
) -> Sequence[ChatCompletionMessage]:
    """Add cache_control inside content blocks for Vertex AI/Gemini caching.

    Gemini requires cache_control to be on a content block within the content array,
    not at the message level. This function converts string content to the array format
    and adds cache_control to the last content block in each cacheable message.
    """
    updated: list[ChatCompletionMessage] = []
    for message in messages:
        mutated = dict(message)
        content = mutated.get("content")

        if isinstance(content, str):
            # Convert string content to array format with cache_control
            mutated["content"] = [
                {
                    "type": "text",
                    "text": content,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
        elif isinstance(content, list) and content:
            # Content is already an array - add cache_control to last block
            new_content = []
            for i, block in enumerate(content):
                if isinstance(block, dict):
                    block_copy = dict(block)
                    # Add cache_control to the last content block
                    if i == len(content) - 1:
                        block_copy["cache_control"] = {"type": "ephemeral"}
                    new_content.append(block_copy)
                else:
                    new_content.append(block)
            mutated["content"] = new_content

        updated.append(revalidate_message_from_original(message, mutated))
    return updated
