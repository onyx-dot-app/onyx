from datetime import datetime
from datetime import timezone

from onyx.configs.constants import MessageType
from onyx.server.query_and_chat.context_usage import compute_context_usage
from onyx.server.query_and_chat.models import ChatMessageDetail


def _msg(
    message_id: int,
    message_type: MessageType,
    prompt_tokens: int | None,
) -> ChatMessageDetail:
    return ChatMessageDetail(
        message_id=message_id,
        message="",
        message_type=message_type,
        time_sent=datetime.now(timezone.utc),
        files=[],
        prompt_tokens=prompt_tokens,
    )


def test_uses_last_reported_assistant_prompt_tokens() -> None:
    messages = [
        _msg(1, MessageType.USER, None),
        _msg(2, MessageType.ASSISTANT, 5000),
    ]
    usage = compute_context_usage(messages, lambda: 128000)
    assert usage is not None
    assert usage.used_tokens == 5000
    assert usage.max_input_tokens == 128000


def test_backtracks_to_most_recent_reporting_turn() -> None:
    # Latest assistant turn has no usage; fall back to the last one that did.
    messages = [
        _msg(1, MessageType.ASSISTANT, 4000),
        _msg(2, MessageType.ASSISTANT, None),
    ]
    usage = compute_context_usage(messages, lambda: 128000)
    assert usage is not None
    assert usage.used_tokens == 4000


def test_none_when_no_reporting_turn() -> None:
    # user-only history: no assistant message with prompt_tokens -> no gauge.
    usage = compute_context_usage([_msg(1, MessageType.USER, None)], lambda: 128000)
    assert usage is None


def test_none_for_empty_history() -> None:
    assert compute_context_usage([], lambda: 128000) is None


def test_max_input_tokens_fn_not_resolved_without_a_turn() -> None:
    # No reporting turn -> the (potentially expensive) LLM resolution is skipped.
    def _exploding() -> int:
        raise AssertionError("max_input_tokens_fn must not run without a turn")

    assert compute_context_usage([_msg(1, MessageType.USER, None)], _exploding) is None


def test_none_when_max_input_tokens_non_positive() -> None:
    messages = [_msg(1, MessageType.ASSISTANT, 5000)]
    assert compute_context_usage(messages, lambda: 0) is None
