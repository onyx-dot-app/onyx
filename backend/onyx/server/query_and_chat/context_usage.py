from collections.abc import Callable

from onyx.configs.constants import MessageType
from onyx.server.query_and_chat.models import ChatMessageDetail
from onyx.server.query_and_chat.models import ContextUsage


def compute_context_usage(
    messages: list[ChatMessageDetail],
    max_input_tokens_fn: Callable[[], int],
) -> ContextUsage | None:
    """Most recent assistant turn that reported a real prompt size, or None when
    none has (so a fresh chat shows no gauge). max_input_tokens_fn is resolved only
    when there's a turn to report, keeping LLM resolution off the empty-chat path."""
    last_reported_tokens = next(
        (
            m.prompt_tokens
            for m in reversed(messages)
            if m.message_type == MessageType.ASSISTANT and m.prompt_tokens is not None
        ),
        None,
    )
    if last_reported_tokens is None:
        return None
    max_input_tokens = max_input_tokens_fn()
    if max_input_tokens <= 0:
        return None
    return ContextUsage(
        used_tokens=last_reported_tokens,
        max_input_tokens=max_input_tokens,
    )
