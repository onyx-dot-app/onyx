from collections.abc import Callable

from onyx.chat.models import ChatMessageSimple
from onyx.configs.constants import MessageType
from onyx.llm.exceptions import InputBudgetExceededError

TOOL_RESULT_TRUNCATION_NOTICE = (
    "\n\n[Tool result truncated. This is an incomplete text excerpt.]"
)


def shorten_tool_result(
    text: str,
    max_tokens: int,
    token_counter: Callable[[str], int],
    token_count: int | None = None,
) -> tuple[str, int]:
    count = token_counter(text) if token_count is None else token_count
    if count <= max_tokens:
        return text, count
    notice_tokens = token_counter(TOOL_RESULT_TRUNCATION_NOTICE)
    if max_tokens < notice_tokens:
        raise InputBudgetExceededError()

    original = text.removesuffix(TOOL_RESULT_TRUNCATION_NOTICE)
    prefix_length = min(
        len(original), len(original) * (max_tokens - notice_tokens) // count
    )
    while prefix_length:
        candidate = original[:prefix_length] + TOOL_RESULT_TRUNCATION_NOTICE
        candidate_tokens = token_counter(candidate)
        if candidate_tokens <= max_tokens:
            return candidate, candidate_tokens
        # Token counts need not be monotonic across character boundaries.
        prefix_length = min(
            prefix_length - 1, prefix_length * max_tokens // candidate_tokens
        )
    return TOOL_RESULT_TRUNCATION_NOTICE, notice_tokens


def fit_tool_results(
    messages: list[ChatMessageSimple],
    max_tokens: int,
    token_counter: Callable[[str], int],
) -> list[ChatMessageSimple]:
    total_tokens = sum(message.token_count for message in messages)
    if total_tokens <= max_tokens:
        return messages

    result_indices = [
        index
        for index, message in enumerate(messages)
        if message.message_type == MessageType.TOOL_CALL_RESPONSE
    ]
    notice_tokens = token_counter(TOOL_RESULT_TRUNCATION_NOTICE)
    last_call_index = max(
        (index for index, message in enumerate(messages) if message.tool_calls),
        default=-1,
    )
    current_indices = [index for index in result_indices if index > last_call_index]

    def capacity(indices: list[int]) -> int:
        return (
            max_tokens
            - total_tokens
            + sum(messages[index].token_count for index in indices)
        )

    def minimum(indices: list[int]) -> int:
        return sum(min(messages[index].token_count, notice_tokens) for index in indices)

    # Preserve earlier cycles when the current batch can absorb the deficit.
    indices = (
        current_indices
        if current_indices and capacity(current_indices) >= minimum(current_indices)
        else result_indices
    )
    remaining = capacity(indices)
    if not indices or remaining < minimum(indices):
        raise InputBudgetExceededError()

    allowances: dict[int, int] = {}
    pending = sorted(indices, key=lambda index: messages[index].token_count)
    while pending and messages[pending[0]].token_count <= remaining // len(pending):
        index = pending.pop(0)
        allowances[index] = messages[index].token_count
        remaining -= allowances[index]
    if pending:
        share, extra = divmod(remaining, len(pending))
        for order, index in enumerate(sorted(pending)):
            allowances[index] = share + (order < extra)

    result = messages.copy()
    for index in indices:
        message = messages[index]
        text, count = shorten_tool_result(
            message.message, allowances[index], token_counter, message.token_count
        )
        result[index] = message.model_copy(
            update={"message": text, "token_count": count}
        )
    return result
