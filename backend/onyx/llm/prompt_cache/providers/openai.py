"""OpenAI provider adapter for prompt caching.

OpenAI caches prompt prefixes implicitly. Requests on the OpenAI API to models
that LiteLLM's `supports_openai_prompt_cache_breakpoint` accepts also carry
explicit prompt_cache_breakpoints on every tool result
(`explicit_cache_breakpoints`, applied in `multi_llm.py`).
"""

from collections.abc import Iterable, Sequence
from functools import lru_cache

from pydantic import JsonValue

from onyx.configs.model_configs import ENABLE_PROMPT_CACHING
from onyx.llm.model_request import (
    ChatCompletionMessage,
    ResponsesInputText,
    ToolMessage,
)
from onyx.llm.prompt_cache.models import CacheMetadata
from onyx.llm.prompt_cache.providers.base import PromptCacheProvider
from onyx.llm.prompt_cache.utils import prepare_messages_with_cacheable_transform

# Both the breakpoint on a tool result and the request's prompt_cache_options.
EXPLICIT_CACHE_MODE: dict[str, JsonValue] = {"mode": "explicit"}


def uses_explicit_cache_breakpoints(
    model_names: Iterable[str], api_base: str | None
) -> bool:
    """Whether requests for this model carry explicit breakpoints: prompt caching
    is on, the model supports them, and the request goes to the OpenAI API."""
    if not ENABLE_PROMPT_CACHING:
        return False
    from litellm.integrations.anthropic_cache_control_hook import targets_openai_api

    return _supports_breakpoint(tuple(model_names)) and targets_openai_api(api_base)


@lru_cache(maxsize=256)
def _supports_breakpoint(model_names: tuple[str, ...]) -> bool:
    from litellm.integrations.anthropic_cache_control_hook import (
        supports_openai_prompt_cache_breakpoint,
    )

    return any(supports_openai_prompt_cache_breakpoint(name) for name in model_names)


def explicit_cache_breakpoints(
    messages: Sequence[ChatCompletionMessage],
) -> tuple[list[ChatCompletionMessage], dict[str, JsonValue] | None]:
    """The messages with every tool result marked with an explicit breakpoint,
    and the request's prompt_cache_options; None before the first tool result,
    so that request keeps implicit caching.

    A breakpoint is part of the cached prefix, so an entry is reused only if
    the same message still carries the marker. Marking each tool result
    (not only the last) keeps earlier bytes identical from step to step.
    Only tool output can carry the marker through LiteLLM: user content must
    be chat-completions ``text`` (whose extra keys the bridge drops), system
    messages become ``instructions``, and assistant output does not accept
    one.
    """
    result = list(messages)
    marked = False
    for index, message in enumerate(result):
        if not isinstance(message, ToolMessage):
            continue
        text = (
            message.content
            if isinstance(message.content, str)
            else "".join(part.text for part in message.content)
        )
        result[index] = message.model_copy(
            update={
                "content": [
                    ResponsesInputText(
                        text=text, prompt_cache_breakpoint=EXPLICIT_CACHE_MODE
                    )
                ]
            }
        )
        marked = True
    return result, EXPLICIT_CACHE_MODE if marked else None


class OpenAIPromptCacheProvider(PromptCacheProvider):
    """OpenAI adapter for implicit prompt caching.

    Explicit tool-result breakpoints come from `explicit_cache_breakpoints`.
    """

    def supports_caching(self) -> bool:
        """OpenAI supports automatic prompt caching."""
        return True

    def prepare_messages_for_caching(
        self,
        cacheable_prefix: list[ChatCompletionMessage] | None,
        suffix: list[ChatCompletionMessage],
        continuation: bool,
        cache_metadata: CacheMetadata | None,  # noqa: ARG002
    ) -> list[ChatCompletionMessage]:
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

    def extract_cache_metadata(
        self,
        response: dict,  # noqa: ARG002
        cache_key: str,  # noqa: ARG002
    ) -> CacheMetadata | None:
        """Extract cache metadata from OpenAI response.

        OpenAI responses may include cached_tokens in the usage field.
        For implicit caching, we don't need to store much metadata.

        Args:
            response: OpenAI API response dictionary
            cache_key: Cache key used for this request

        Returns:
            CacheMetadata if extractable, None otherwise
        """
        # For implicit caching, OpenAI handles everything automatically
        # We could extract cached_tokens from response.get("usage", {}).get("cached_tokens")
        # but for now, we don't need to store metadata for implicit caching
        return None

    def get_cache_ttl_seconds(self) -> int:
        """Get cache TTL for OpenAI (1 hour max)."""
        return 3600
