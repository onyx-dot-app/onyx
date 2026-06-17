from collections.abc import Callable

from onyx.configs.constants import MessageType
from onyx.server.query_and_chat.models import ChatMessageDetail
from onyx.server.query_and_chat.models import ContextUsage


def compute_context_usage(
    messages: list[ChatMessageDetail],
    max_input_tokens_fn: Callable[[], int],
) -> ContextUsage | None:
    """Most recent assistant turn that reported a real prompt size, or None when
    none has (so a fresh chat shows no gauge). The denominator persisted with the
    turn is preferred so a mid-chat model switch doesn't repaint the gauge against
    the current persona's window; pre-migration rows (no stored window) fall back
    to the current model's, resolved lazily off the empty-chat path."""
    last_reported = next(
        (
            m
            for m in reversed(messages)
            if m.message_type == MessageType.ASSISTANT and m.prompt_tokens is not None
        ),
        None,
    )
    if last_reported is None:
        return None
    used_tokens = last_reported.prompt_tokens
    if used_tokens is None:
        return None
    max_input_tokens = last_reported.max_input_tokens or max_input_tokens_fn()
    if max_input_tokens <= 0:
        return None
    return ContextUsage(
        used_tokens=used_tokens,
        max_input_tokens=max_input_tokens,
    )
