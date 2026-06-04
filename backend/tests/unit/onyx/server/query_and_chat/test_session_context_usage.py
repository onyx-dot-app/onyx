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


def test_uses_last_assistant_prompt_tokens() -> None:
    messages = [
        _msg(1, MessageType.USER, None),
        _msg(2, MessageType.ASSISTANT, 5000),
    ]

    # baseline_fn must NOT be invoked when a real last turn exists — proving the
    # expensive baseline tokenization stays off the common hot path.
    def _exploding_baseline() -> int:
        raise AssertionError("baseline_fn should not be called when a turn exists")

    usage = compute_context_usage(
        messages, max_input_tokens=128000, baseline_fn=_exploding_baseline
    )

    assert usage.used_tokens == 5000
    assert usage.max_input_tokens == 128000
    assert usage.is_baseline is False


def test_baseline_fn_not_called_with_last_turn() -> None:
    messages = [
        _msg(1, MessageType.USER, None),
        _msg(2, MessageType.ASSISTANT, 5000),
    ]
    calls = 0

    def _counting_baseline() -> int:
        nonlocal calls
        calls += 1
        return 100

    compute_context_usage(
        messages, max_input_tokens=128000, baseline_fn=_counting_baseline
    )

    assert calls == 0


def test_falls_back_to_baseline_when_no_assistant_turn() -> None:
    # user-only history: no assistant message with prompt_tokens
    messages = [_msg(1, MessageType.USER, None)]

    usage = compute_context_usage(
        messages, max_input_tokens=128000, baseline_fn=lambda: 100
    )

    assert usage.used_tokens == 100
    assert usage.max_input_tokens == 128000
    assert usage.is_baseline is True


def test_falls_back_to_baseline_for_empty_history() -> None:
    usage = compute_context_usage([], max_input_tokens=128000, baseline_fn=lambda: 250)

    assert usage.used_tokens == 250
    assert usage.is_baseline is True
