from __future__ import annotations

from contextlib import nullcontext
from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.configs.constants import MessageType
from onyx.llm.models import UserMessage
from onyx.secondary_llm_flows.time_filter import _parse_time_decision
from onyx.secondary_llm_flows.time_filter import decide_time_filter
from onyx.secondary_llm_flows.time_filter import TimeFilter
from onyx.tools.models import ChatMinimalTextMessage


def _run_decision(
    history: list[ChatMinimalTextMessage],
    llm_returns: str,
) -> tuple[TimeFilter, list]:
    """Run decide_time_filter with the LLM stubbed to return `llm_returns`.
    Returns ((start, end), prompt_messages)."""
    captured: dict = {}

    def fake_invoke(prompt: list, **_kwargs: object) -> MagicMock:
        captured["prompt"] = prompt
        resp = MagicMock()
        resp.choice.message.content = llm_returns
        return resp

    llm = MagicMock()
    llm.invoke.side_effect = fake_invoke
    with (
        patch(
            "onyx.secondary_llm_flows.time_filter.llm_generation_span",
            return_value=nullcontext(MagicMock()),
        ),
        patch("onyx.secondary_llm_flows.time_filter.record_llm_response"),
    ):
        tf = decide_time_filter(history, llm)
    return tf, captured.get("prompt", [])


# ---- _parse_time_decision (pure parsing, no LLM) ----


def test_no_bounds_pair_has_no_bounds() -> None:
    assert _parse_time_decision("(None, None)") == (None, None)


def test_lower_bound_only() -> None:
    start, end = _parse_time_decision("(2025-03-01, None)")
    assert start is not None and start.isoformat() == "2025-03-01T00:00:00+00:00"
    assert end is None


def test_upper_bound_only() -> None:
    start, end = _parse_time_decision("(None, 2022-12-31)")
    assert start is None
    # End is pushed to the end of the day so a <= comparison includes the whole day.
    assert end is not None and end.isoformat() == "2022-12-31T23:59:59.999999+00:00"


def test_single_day_is_a_full_day_range() -> None:
    start, end = _parse_time_decision("(2024-03-25, 2024-03-25)")
    assert start is not None and start.isoformat() == "2024-03-25T00:00:00+00:00"
    assert end is not None and end.isoformat() == "2024-03-25T23:59:59.999999+00:00"


def test_named_month_becomes_full_span_range() -> None:
    start, end = _parse_time_decision("(2025-01-01, 2025-01-31)")
    assert start is not None and start.isoformat() == "2025-01-01T00:00:00+00:00"
    assert end is not None and end.date().isoformat() == "2025-01-31"


def test_pair_is_extracted_from_surrounding_text() -> None:
    """The pair is recovered even when the model adds fences or prose."""
    start, end = _parse_time_decision("```\n(2025-01-01, 2025-01-31)\n```")
    assert start is not None and end is not None
    assert start.date().isoformat() == "2025-01-01"


def test_quoted_dates_are_parsed() -> None:
    start, end = _parse_time_decision('("2025-03-01", None)')
    assert start is not None and start.date().isoformat() == "2025-03-01"
    assert end is None


def test_malformed_output_has_no_bounds() -> None:
    assert _parse_time_decision("not a pair at all") == (None, None)


def test_empty_content_has_no_bounds() -> None:
    assert _parse_time_decision("") == (None, None)
    assert _parse_time_decision(None) == (None, None)


def test_unparseable_dates_have_no_bounds() -> None:
    """A pair whose sides aren't dates yields no usable bound."""
    assert _parse_time_decision("(banana, None)") == (None, None)


# ---- decide_time_filter (prompt construction + LLM stub) ----


def test_prompt_is_single_user_message_and_excludes_assistant_turns() -> None:
    history = [
        ChatMinimalTextMessage(
            message="What changed last January?", message_type=MessageType.USER
        ),
        ChatMinimalTextMessage(
            message="Let me look into that.", message_type=MessageType.ASSISTANT
        ),
    ]
    (start, end), prompt = _run_decision(history, "(2026-01-01, 2026-01-31)")
    assert all(isinstance(m, UserMessage) for m in prompt)
    text = prompt[-1].content
    assert "What changed last January?" in text
    assert "Let me look into that." not in text
    assert start is not None and end is not None


def test_no_user_turns_skips_the_llm() -> None:
    llm = MagicMock()
    history = [
        ChatMinimalTextMessage(
            message="assistant only", message_type=MessageType.ASSISTANT
        )
    ]
    assert decide_time_filter(history, llm) == (None, None)
    llm.invoke.assert_not_called()


def test_only_the_last_five_user_turns_reach_the_prompt() -> None:
    history = [
        ChatMinimalTextMessage(message=f"msg {i}", message_type=MessageType.USER)
        for i in range(8)
    ]
    _tf, prompt = _run_decision(history, "(None, None)")
    text = prompt[-1].content
    assert "msg 7" in text and "msg 3" in text
    assert "msg 2" not in text and "msg 0" not in text
