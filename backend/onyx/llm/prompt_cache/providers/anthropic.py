"""Anthropic provider adapter for prompt caching."""

from collections.abc import Sequence

from onyx.llm.interfaces import LanguageModelInput
from onyx.llm.models import ChatCompletionMessage
from onyx.llm.prompt_cache.models import CacheMetadata
from onyx.llm.prompt_cache.providers.base import PromptCacheProvider
from onyx.llm.prompt_cache.utils import prepare_messages_with_cacheable_transform
from onyx.llm.prompt_cache.utils import revalidate_message_from_original


def _add_anthropic_cache_control(
    messages: Sequence[ChatCompletionMessage],
) -> Sequence[ChatCompletionMessage]:
    """Add cache_control parameter to messages for Anthropic caching.

    Args:
        messages: Messages to transform

    Returns:
        Messages with cache_control added
    """
    last_message_dict = dict(messages[-1])
    last_message_dict["cache_control"] = {"type": "ephemeral"}
    last_message = revalidate_message_from_original(
        original=messages[-1], mutated=last_message_dict
    )
    return list(messages[:-1]) + [last_message]


class AnthropicPromptCacheProvider(PromptCacheProvider):
    """Anthropic adapter for prompt caching (explicit caching with cache_control).
    implicit caching = just need to ensure byte-equivalent prefixes, and the provider
                       auto-detects and reuses them.
    explicit caching = the caller must do _something_ to enable provider-side caching.
    In this case, anthropic supports explicit caching via the cache_control parameter:
    https://platform.claude.com/docs/en/build-with-claude/prompt-caching
    """

    def supports_caching(self) -> bool:
        """Anthropic supports explicit prompt caching."""
        return True

    def prepare_messages_for_caching(
        self,
        cacheable_prefix: LanguageModelInput | None,
        suffix: LanguageModelInput,
        continuation: bool,
        cache_metadata: CacheMetadata | None,
    ) -> LanguageModelInput:
        """Prepare messages for Anthropic caching.

        Anthropic requires cache_control parameter on cacheable messages.
        We add cache_control={"type": "ephemeral"} to all cacheable prefix messages.

        Args:
            cacheable_prefix: Optional cacheable prefix
            suffix: Non-cacheable suffix
            continuation: Whether to append suffix to last prefix message
            cache_metadata: Cache metadata (for future explicit caching support)

        Returns:
            Combined messages with cache_control on cacheable messages
        """
        return prepare_messages_with_cacheable_transform(
            cacheable_prefix=cacheable_prefix,
            suffix=suffix,
            continuation=continuation,
            transform_cacheable=_add_anthropic_cache_control,
        )

    def extract_cache_metadata(
        self,
        response: dict,
        cache_key: str,
    ) -> CacheMetadata | None:
        """Extract cache metadata from Anthropic response.

        Anthropic may return cache identifiers in the response.
        For now, we don't extract detailed metadata (future explicit caching support).

        Args:
            response: Anthropic API response dictionary
            cache_key: Cache key used for this request

        Returns:
            CacheMetadata if extractable, None otherwise
        """
        # TODO: Extract cache identifiers from response when implementing explicit caching
        return None

    def get_cache_ttl_seconds(self) -> int:
        """Get cache TTL for Anthropic (5 minutes default)."""
        return 300
