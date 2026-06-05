from collections.abc import Callable
from typing import TYPE_CHECKING

from pydantic import BaseModel

from onyx.configs.constants import MessageType

if TYPE_CHECKING:
    # Imported under TYPE_CHECKING only: models.py imports ContextUsage from this
    # module for its response field, so importing ChatMessageDetail at runtime
    # would create a circular import.
    from onyx.server.query_and_chat.models import ChatMessageDetail


class ContextUsage(BaseModel):
    used_tokens: (
        int  # provider prompt_tokens of the last turn, OR baseline for an empty chat
    )
    max_input_tokens: int  # the producing model's context window
    is_baseline: bool = (
        False  # True when used_tokens is the empty-chat estimate (no real turn yet)
    )


def compute_context_usage(
    messages: "list[ChatMessageDetail]",
    max_input_tokens: int,
    baseline_fn: Callable[[], int],
) -> "ContextUsage":
    """Last assistant turn's real prompt size, or the baseline if no turn yet.

    baseline_fn is only invoked for empty/never-answered chats — keeping the
    expensive system-prompt tokenization off the common (non-empty) hot path.
    """
    last = next(
        (
            m
            for m in reversed(messages)
            if m.message_type == MessageType.ASSISTANT and m.prompt_tokens is not None
        ),
        None,
    )
    if last is not None and last.prompt_tokens is not None:
        return ContextUsage(
            used_tokens=last.prompt_tokens,
            max_input_tokens=max_input_tokens,
            is_baseline=False,
        )
    return ContextUsage(
        used_tokens=baseline_fn(),
        max_input_tokens=max_input_tokens,
        is_baseline=True,
    )
