"""Utility functions for prompt caching."""

from collections.abc import Callable
from collections.abc import Sequence
from typing import cast

from onyx.llm.interfaces import LanguageModelInput
from onyx.llm.message_types import ChatCompletionMessage
from onyx.llm.message_types import UserMessageWithText


def normalize_language_model_input(
    input: LanguageModelInput,
) -> Sequence[ChatCompletionMessage]:
    """Normalize LanguageModelInput to Sequence[ChatCompletionMessage].

    Args:
        input: LanguageModelInput (str or Sequence[ChatCompletionMessage])

    Returns:
        Sequence of ChatCompletionMessage objects
    """
    if isinstance(input, str):
        # Convert string to user message
        return [UserMessageWithText(role="user", content=input)]
    else:
        return input


def combine_messages_with_continuation(
    prefix_msgs: Sequence[ChatCompletionMessage],
    suffix_msgs: Sequence[ChatCompletionMessage],
    continuation: bool,
    was_prefix_string: bool,
) -> Sequence[ChatCompletionMessage]:
    """Combine prefix and suffix messages, handling continuation flag.

    Args:
        prefix_msgs: Normalized cacheable prefix messages
        suffix_msgs: Normalized suffix messages
        continuation: If True and prefix is not a string, append suffix content
            to the last message of prefix
        was_prefix_string: Whether the original prefix was a string (strings
            remain in their own content block even if continuation=True)

    Returns:
        Combined messages
    """
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

        result[-1] = cast(ChatCompletionMessage, last_msg)
        result.extend(suffix_msgs[1:])
        return result

    # Simple concatenation (or prefix was a string, so keep separate)
    return list(prefix_msgs) + list(suffix_msgs)


def prepare_messages_with_cacheable_transform(
    cacheable_prefix: LanguageModelInput | None,
    suffix: LanguageModelInput,
    continuation: bool,
    transform_cacheable: (
        Callable[[Sequence[ChatCompletionMessage]], Sequence[ChatCompletionMessage]]
        | None
    ) = None,
) -> LanguageModelInput:
    """Prepare messages for caching with optional transformation of cacheable prefix.

    This is a shared utility that handles the common flow:
    1. Normalize inputs
    2. Optionally transform cacheable messages
    3. Combine with continuation handling

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

    prefix_msgs = normalize_language_model_input(cacheable_prefix)
    suffix_msgs = normalize_language_model_input(suffix)

    # Apply transformation to cacheable messages if provided
    if transform_cacheable is not None:
        prefix_msgs = transform_cacheable(prefix_msgs)

    # Handle continuation flag
    was_prefix_string = isinstance(cacheable_prefix, str)

    return combine_messages_with_continuation(
        prefix_msgs, suffix_msgs, continuation, was_prefix_string
    )
