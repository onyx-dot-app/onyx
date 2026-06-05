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
    """Most recent assistant turn that reported a real prompt size, else the baseline.

    A turn lacks prompt_tokens when its provider returned no usage; falling back to
    the last turn that did report is a closer estimate of the live context than
    re-deriving the baseline. baseline_fn is invoked only when no assistant turn has
    a recorded prompt size (empty chats, or history predating this column) — keeping
    the expensive system-prompt tokenization off the common hot path.
    """
    last_reported_tokens = next(
        (
            m.prompt_tokens
            for m in reversed(messages)
            if m.message_type == MessageType.ASSISTANT and m.prompt_tokens is not None
        ),
        None,
    )
    if last_reported_tokens is not None:
        return ContextUsage(
            used_tokens=last_reported_tokens,
            max_input_tokens=max_input_tokens,
            is_baseline=False,
        )
    return ContextUsage(
        used_tokens=baseline_fn(),
        max_input_tokens=max_input_tokens,
        is_baseline=True,
    )
