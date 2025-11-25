"""Utility functions for prompt caching."""

from collections.abc import Callable
from collections.abc import Sequence
from typing import cast
from typing import TYPE_CHECKING

from onyx.llm.interfaces import LanguageModelInput
from onyx.llm.interfaces import LLM
from onyx.llm.message_types import ChatCompletionMessage
from onyx.llm.message_types import UserMessageWithText
from onyx.utils.logger import setup_logger

if TYPE_CHECKING:
    from onyx.agents.agent_sdk.message_types import AgentSDKMessage

logger = setup_logger()


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


def apply_prompt_caching_to_agent_messages(
    messages: list["AgentSDKMessage"],
    llm: LLM,
) -> list["AgentSDKMessage"]:
    """Apply prompt caching to agent SDK messages.

    MINIMAL MODIFICATIONS ONLY: This function adds cache control parameters where needed,
    but otherwise returns messages unchanged.

    For OpenAI/Vertex (implicit caching): Messages pass through unchanged
    For Anthropic: Adds cache_control parameter to the last cacheable message

    Args:
        messages: List of agent SDK messages (system, history, current user message)
        llm: The LLM instance (used to determine provider)

    Returns:
        List of agent SDK messages with minimal caching modifications
    """
    from onyx.llm.prompt_cache.providers.factory import get_provider_adapter

    if not messages:
        return messages

    provider_adapter = get_provider_adapter(llm.config.model_provider)

    # For providers that don't support caching or use implicit caching (OpenAI, Vertex),
    # return messages unchanged
    if not provider_adapter.supports_caching():
        return messages

    # Check if this provider needs explicit cache control (Anthropic)
    # For now, only Anthropic needs explicit cache_control parameters
    if llm.config.model_provider != "anthropic":
        # OpenAI and Vertex use implicit caching, no modifications needed
        return messages

    # For Anthropic: Add cache_control to the last message before the final user message
    # Find the last user message
    last_user_msg_idx = -1
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "user":  # type: ignore
            last_user_msg_idx = i
            break

    if last_user_msg_idx <= 0:
        # No user message or it's the first message, no caching
        return messages

    # Add cache_control to the message just before the last user message
    cache_breakpoint_idx = last_user_msg_idx - 1

    # Create a shallow copy of messages to avoid mutating the input
    result_messages = list(messages)

    # Add cache_control to the breakpoint message
    breakpoint_msg = dict(result_messages[cache_breakpoint_idx])

    # For Anthropic, add cache_control as a top-level field
    breakpoint_msg["cache_control"] = {"type": "ephemeral"}  # type: ignore

    result_messages[cache_breakpoint_idx] = breakpoint_msg  # type: ignore

    logger.debug(
        f"Added cache_control to message at index {cache_breakpoint_idx} "
        f"for provider {llm.config.model_provider}"
    )

    return result_messages
