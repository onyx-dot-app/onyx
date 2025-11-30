"""No-op provider adapter for providers without caching support."""

from onyx.llm.interfaces import LanguageModelInput
from onyx.llm.prompt_cache.interfaces import CacheMetadata
from onyx.llm.prompt_cache.providers.base import PromptCacheProvider
from onyx.llm.prompt_cache.utils import normalize_language_model_input


class NoOpPromptCacheProvider(PromptCacheProvider):
    """No-op adapter for providers that don't support prompt caching."""

    def supports_caching(self) -> bool:
        """No-op providers don't support caching."""
        return False

    def prepare_messages_for_caching(
        self,
        cacheable_prefix: LanguageModelInput | None,
        suffix: LanguageModelInput,
        continuation: bool,
        cache_metadata: CacheMetadata | None,
    ) -> LanguageModelInput:
        """Return messages unchanged (no caching support).

        Args:
            cacheable_prefix: Optional cacheable prefix (can be str or Sequence[ChatCompletionMessage])
            suffix: Non-cacheable suffix (can be str or Sequence[ChatCompletionMessage])
            continuation: Whether to append suffix to last prefix message.
                Note: When cacheable_prefix is a string, it remains in its own content block.
            cache_metadata: Cache metadata (ignored)

        Returns:
            Combined messages (prefix + suffix)
        """
        # Normalize inputs
        if cacheable_prefix is None:
            return suffix

        prefix_msgs = normalize_language_model_input(cacheable_prefix)
        suffix_msgs = normalize_language_model_input(suffix)

        # Handle continuation flag
        # Special case: if cacheable_prefix was originally a string, keep it in its own block
        was_prefix_string = isinstance(cacheable_prefix, str)

        if continuation and prefix_msgs and not was_prefix_string:
            # Append suffix content to last message of prefix
            result = list(prefix_msgs)
            last_msg = dict(result[-1])
            suffix_first = dict(suffix_msgs[0]) if suffix_msgs else {}

            # Combine content
            if "content" in last_msg and "content" in suffix_first:
                if isinstance(last_msg["content"], str) and isinstance(
                    suffix_first["content"], str
                ):
                    last_msg["content"] = last_msg["content"] + suffix_first["content"]
                else:
                    # Handle list content (multimodal)
                    prefix_content = (
                        last_msg["content"]
                        if isinstance(last_msg["content"], list)
                        else [{"type": "text", "text": last_msg["content"]}]
                    )
                    suffix_content = (
                        suffix_first["content"]
                        if isinstance(suffix_first["content"], list)
                        else [{"type": "text", "text": suffix_first["content"]}]
                    )
                    last_msg["content"] = prefix_content + suffix_content

            result[-1] = last_msg
            result.extend(suffix_msgs[1:])
            return result

        # Simple concatenation (or prefix was a string, so keep separate)
        return list(prefix_msgs) + list(suffix_msgs)

    def extract_cache_metadata(
        self,
        response: dict,
        cache_key: str,
    ) -> CacheMetadata | None:
        """No cache metadata to extract."""
        return None

    def get_cache_ttl_seconds(self) -> int:
        """Return default TTL (not used for no-op)."""
        return 0
