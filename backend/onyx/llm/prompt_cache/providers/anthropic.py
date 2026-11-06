"""Anthropic provider adapter for prompt caching."""

from collections.abc import Sequence

from onyx.llm.model_request import ChatCompletionMessage, UserMessage
from onyx.llm.prompt_cache.models import CacheMetadata
from onyx.llm.prompt_cache.providers.base import PromptCacheProvider
from onyx.llm.prompt_cache.utils import prepare_messages_with_cacheable_transform


def _add_anthropic_cache_control(
    messages: Sequence[ChatCompletionMessage],
) -> Sequence[ChatCompletionMessage]:
    """Mark the head, context before the newest question, and the prefix tail.

    The context breakpoint allows different questions to reuse shared files.
    The tail also caches the question and tool rounds as the conversation grows.
    These boundaries use at most three of Anthropic's four breakpoints.
    """
    result = list(messages)
    if not result:
        return result
    latest_user = next(
        (
            index
            for index in range(len(result) - 1, -1, -1)
            if isinstance(result[index], UserMessage)
        ),
        0,
    )
    boundaries = {0, len(result) - 1}
    if latest_user > 0:
        boundaries.add(latest_user - 1)
    for index in boundaries:
        message = result[index]
        cache_control = {"type": "ephemeral"}
        if isinstance(message.content, list):
            if not message.content:
                continue
            content = [
                *message.content[:-1],
                message.content[-1].model_copy(update={"cache_control": cache_control}),
            ]
            result[index] = message.model_copy(
                update={"content": content, "cache_control": None}
            )
        else:
            result[index] = message.model_copy(update={"cache_control": cache_control})
    return result


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
        cacheable_prefix: list[ChatCompletionMessage] | None,
        suffix: list[ChatCompletionMessage],
        continuation: bool,
        cache_metadata: CacheMetadata | None,  # noqa: ARG002
    ) -> list[ChatCompletionMessage]:
        """Prepare messages for Anthropic caching.

        Anthropic requires cache_control parameter on cacheable messages.
        We mark the head, context boundary, and tail of the cacheable prefix.

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
        response: dict,  # noqa: ARG002
        cache_key: str,  # noqa: ARG002
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
