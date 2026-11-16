"""OpenAI provider adapter for prompt caching.

OpenAI caches prompt prefixes implicitly. Requests on OpenAI or Azure APIs to models
that LiteLLM's `supports_openai_prompt_cache_breakpoint` accepts instead carry
explicit prompt_cache_breakpoints on every user message of the cacheable prefix
and on every tool result (`explicit_cache_breakpoints`, applied in
`multi_llm.py`).
"""

from collections.abc import Iterable, Sequence
from functools import lru_cache
from urllib.parse import urlparse

from pydantic import JsonValue

from onyx.llm.model_request import ChatCompletionMessage, UserMessage
from onyx.llm.prompt_cache.models import CacheMetadata
from onyx.llm.prompt_cache.providers.base import PromptCacheProvider
from onyx.llm.prompt_cache.utils import prepare_messages_with_cacheable_transform

# Both the breakpoint on a tool result and the request's prompt_cache_options.
EXPLICIT_CACHE_MODE: dict[str, JsonValue] = {"mode": "explicit"}


def uses_explicit_cache_breakpoints(
    model_names: Iterable[str], api_base: str | None, *, azure: bool = False
) -> bool:
    """Check model and endpoint support while holding the environment lock."""
    if not _supports_breakpoint(tuple(model_names)):
        return False
    import litellm
    from litellm.integrations.anthropic_cache_control_hook import targets_openai_api
    from litellm.secret_managers.main import get_secret_str

    if not azure:
        return targets_openai_api(api_base)
    # Azure resolves a different environment variable from the OpenAI handler.
    endpoint = api_base or litellm.api_base or get_secret_str("AZURE_API_BASE")
    host = urlparse(endpoint).hostname if isinstance(endpoint, str) else None
    return host is not None and host.endswith(
        (".openai.azure.com", ".cognitiveservices.azure.com", ".services.ai.azure.com")
    )


@lru_cache(maxsize=256)
def _supports_breakpoint(model_names: tuple[str, ...]) -> bool:
    from litellm.integrations.anthropic_cache_control_hook import (
        supports_openai_prompt_cache_breakpoint,
    )

    return any(supports_openai_prompt_cache_breakpoint(name) for name in model_names)


# Serialized-message key that carries `CacheableMessage.cache_breakpoint`
# through request transforms. Never sent to a provider.
CACHE_BREAKPOINT_FLAG = "cache_breakpoint"


def without_cache_breakpoint_flags(
    messages: Sequence[dict[str, JsonValue]],
) -> list[dict[str, JsonValue]]:
    """The messages without `CACHE_BREAKPOINT_FLAG`, as a provider receives them."""
    return [
        {key: value for key, value in message.items() if key != CACHE_BREAKPOINT_FLAG}
        if CACHE_BREAKPOINT_FLAG in message
        else message
        for message in messages
    ]


def _marked_text(part: dict[str, JsonValue]) -> dict[str, JsonValue]:
    return {**part, "prompt_cache_breakpoint": dict(EXPLICIT_CACHE_MODE)}


def _marked_user_content(content: JsonValue) -> JsonValue | None:
    """The content with its last text part marked; None if it has no text."""
    if isinstance(content, str):
        return [_marked_text({"type": "text", "text": content})]
    if not isinstance(content, list):
        return None
    for index in range(len(content) - 1, -1, -1):
        part = content[index]
        if isinstance(part, dict) and part.get("type") == "text":
            return [*content[:index], _marked_text(part), *content[index + 1 :]]
    return None


def explicit_cache_breakpoints(
    messages: Sequence[dict[str, JsonValue]],
) -> tuple[list[dict[str, JsonValue]], dict[str, JsonValue] | None]:
    """The messages with explicit breakpoints on every tool result and on the
    user messages that carry `CACHE_BREAKPOINT_FLAG`, and the request's
    prompt_cache_options; None when nothing is marked, so that request keeps
    implicit caching. The flags are removed.

    A breakpoint is part of the cached prefix, so an entry is reused only if
    the same message still carries the marker. Every request marks each user
    message of its cacheable prefix, so later steps and later turns repeat the
    markers of earlier requests and read their entries. Marking each tool
    result (not only the last) keeps earlier bytes identical from step to
    step. Tool output takes the marker on an ``input_text`` part; user content
    must stay chat-completions ``text``, which the patched Responses bridge
    converts with its marker
    (`_patch_responses_bridge_keeps_breakpoints`). System messages become
    ``instructions`` and assistant output does not accept a marker.
    """
    result = without_cache_breakpoint_flags(messages)
    marked = False
    for index, (message, original) in enumerate(zip(result, messages, strict=True)):
        content = message.get("content")
        role = message.get("role")
        if role == "tool" and isinstance(content, str):
            marked_content: JsonValue | None = [
                _marked_text({"type": "input_text", "text": content})
            ]
        elif role == "user" and original.get(CACHE_BREAKPOINT_FLAG) is True:
            marked_content = _marked_user_content(content)
        else:
            continue
        if marked_content is None:
            continue
        result[index] = {**message, "content": marked_content}
        marked = True
    return result, dict(EXPLICIT_CACHE_MODE) if marked else None


def _mark_user_messages(
    messages: Sequence[ChatCompletionMessage],
) -> Sequence[ChatCompletionMessage]:
    """Mark every user message of the cacheable prefix.

    A request reads an entry only at a marker it carries itself. Marking only
    the last user message would drop the marker from earlier user messages on
    the next turn, so that turn could not read the previous turn's entries.
    Tool results carry their own breakpoints."""
    return [
        message.model_copy(update={"cache_breakpoint": True})
        if isinstance(message, UserMessage)
        else message
        for message in messages
    ]


class OpenAIPromptCacheProvider(PromptCacheProvider):
    """OpenAI adapter for implicit prompt caching.

    It flags the user messages of the cacheable prefix;
    `explicit_cache_breakpoints` turns the flags into breakpoints where the
    endpoint accepts them.
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

        Combine the messages and flag every user message of the cacheable
        prefix. The flag is not serialized, so implicit caching sees the same
        messages.

        Args:
            cacheable_prefix: Optional cacheable prefix
            suffix: Non-cacheable suffix
            continuation: Whether to append suffix to last prefix message
            cache_metadata: Cache metadata (ignored for implicit caching)

        Returns:
            Combined messages ready for LLM API call
        """
        return prepare_messages_with_cacheable_transform(
            cacheable_prefix=cacheable_prefix,
            suffix=suffix,
            continuation=continuation,
            transform_cacheable=_mark_user_messages,
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
