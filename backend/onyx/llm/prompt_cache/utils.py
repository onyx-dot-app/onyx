# pyright: reportMissingTypeStubs=false
"""Utility functions for prompt caching."""

from collections.abc import Callable, Sequence
from typing import Any

from onyx.llm.model_request import ChatCompletionMessage, UserMessage
from onyx.llm.models import ContentPart, TextContentPart
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _user_content_with_cache_marker(message: UserMessage) -> list[ContentPart]:
    """Keep a message marker at its original boundary when merging content."""
    content: list[ContentPart] = (
        [TextContentPart(text=message.content)]
        if isinstance(message.content, str)
        else list(message.content)
    )
    if content and message.cache_control is not None:
        content[-1] = content[-1].model_copy(
            update={"cache_control": message.cache_control}
        )
    return content


def combine_messages_with_continuation(
    prefix_msgs: Sequence[ChatCompletionMessage],
    suffix_msgs: Sequence[ChatCompletionMessage],
    continuation: bool,
) -> list[ChatCompletionMessage]:
    """Combine prefix and suffix messages, handling continuation flag.

    Args:
        prefix_msgs: Normalized cacheable prefix messages
        suffix_msgs: Normalized suffix messages
        continuation: If True, append suffix content to the last message of prefix

    Returns:
        Combined messages
    """
    if not continuation or not prefix_msgs:
        return list(prefix_msgs) + list(suffix_msgs)
    if (
        suffix_msgs
        and isinstance(prefix_msgs[-1], UserMessage)
        and isinstance(suffix_msgs[0], UserMessage)
        and (
            prefix_msgs[-1].cache_control is not None
            or suffix_msgs[0].cache_control is not None
        )
    ):
        # Separate blocks preserve both cache boundaries and their lifetimes.
        merged = prefix_msgs[-1].model_copy(
            update={
                "content": _user_content_with_cache_marker(prefix_msgs[-1])
                + _user_content_with_cache_marker(suffix_msgs[0]),
                "cache_control": None,
            }
        )
        return [*prefix_msgs[:-1], merged, *suffix_msgs[1:]]

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

    result[-1] = revalidate_message_from_original(original=result[-1], mutated=last_msg)
    result.extend(suffix_msgs[1:])
    return result


def revalidate_message_from_original(
    original: ChatCompletionMessage,
    mutated: dict[str, Any],
) -> ChatCompletionMessage:
    """Rebuild a mutated message using the original BaseModel type.

    Some providers need to add cache metadata to messages. Re-run validation against
    the original message's Pydantic class so union discrimination (by role) stays
    intact.
    """
    return type(original).model_validate(mutated)


def prepare_messages_with_cacheable_transform(
    cacheable_prefix: list[ChatCompletionMessage] | None,
    suffix: list[ChatCompletionMessage],
    continuation: bool,
    transform_cacheable: (
        Callable[[Sequence[ChatCompletionMessage]], Sequence[ChatCompletionMessage]]
        | None
    ) = None,
) -> list[ChatCompletionMessage]:
    """Prepare messages for caching with optional transformation of cacheable prefix.

    This is a shared utility that handles the common flow:
    1. Optionally transform cacheable messages
    2. Combine with continuation handling

    Args:
        cacheable_prefix: Optional cacheable prefix
        suffix: Non-cacheable suffix
        continuation: Whether to append suffix to last prefix message
        transform_cacheable: Optional function to transform cacheable messages
            (e.g., add cache_control parameter). If None, messages are used as-is.

    Returns:
        Combined messages ready for LLM API call
    """
    if cacheable_prefix is None:
        return suffix

    prefix_msgs = cacheable_prefix

    # Apply transformation to cacheable messages if provided
    if transform_cacheable is not None:
        prefix_msgs = list(transform_cacheable(prefix_msgs))

    return combine_messages_with_continuation(
        prefix_msgs=prefix_msgs, suffix_msgs=suffix, continuation=continuation
    )
