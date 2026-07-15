from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.configs.constants import MessageType
from onyx.llm.models import UserMessage
from onyx.secondary_llm_flows.time_filter import _parse_time_decision
from onyx.secondary_llm_flows.time_filter import decide_time_filter
from onyx.secondary_llm_flows.time_filter import DocumentTimeField
from onyx.secondary_llm_flows.time_filter import TimeFilter
from onyx.tools.models import ChatMinimalTextMessage


def _run_decision(
    history: list[ChatMinimalTextMessage],
    llm_returns: str,
) -> tuple[TimeFilter | None, list]:
    """Run decide_time_filter with the LLM stubbed to return `llm_returns`.
    Returns (TimeFilter | None, prompt_messages)."""
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


def test_no_bounds_pair_is_no_filter() -> None:
    assert _parse_time_decision("updated (None, None)") is None


def test_lower_bound_only_defaults_to_updated() -> None:
    tf = _parse_time_decision("updated (2025-03-01, None)")
    assert tf is not None
    assert tf.field is DocumentTimeField.UPDATED_AT
    assert tf.start is not None and tf.start.isoformat() == "2025-03-01T00:00:00+00:00"
    assert tf.end is None


def test_upper_bound_only() -> None:
    tf = _parse_time_decision("updated (None, 2022-12-31)")
    assert tf is not None
    assert tf.start is None
    # The end bound is pushed to end-of-day to include the whole day.
    assert (
        tf.end is not None and tf.end.isoformat() == "2022-12-31T23:59:59.999999+00:00"
    )


def test_created_intent_is_parsed() -> None:
    tf = _parse_time_decision("created (2025-01-01, 2025-01-31)")
    assert tf is not None
    assert tf.field is DocumentTimeField.CREATED_AT
    assert tf.start is not None and tf.start.date().isoformat() == "2025-01-01"
    assert tf.end is not None and tf.end.date().isoformat() == "2025-01-31"


def test_missing_field_defaults_to_updated() -> None:
    tf = _parse_time_decision("(2025-01-01, 2025-01-31)")
    assert tf is not None
    assert tf.field is DocumentTimeField.UPDATED_AT


def test_single_day_is_a_full_day_range() -> None:
    tf = _parse_time_decision("updated (2024-03-25, 2024-03-25)")
    assert tf is not None
    assert tf.start is not None and tf.start.isoformat() == "2024-03-25T00:00:00+00:00"
    assert (
        tf.end is not None and tf.end.isoformat() == "2024-03-25T23:59:59.999999+00:00"
    )


def test_pair_is_extracted_from_surrounding_text() -> None:
    tf = _parse_time_decision("```\ncreated (2025-01-01, 2025-01-31)\n```")
    assert tf is not None
    assert tf.field is DocumentTimeField.CREATED_AT
    assert tf.start is not None and tf.start.date().isoformat() == "2025-01-01"


def test_quoted_dates_are_parsed() -> None:
    tf = _parse_time_decision('updated ("2025-03-01", None)')
    assert tf is not None
    assert tf.start is not None and tf.start.date().isoformat() == "2025-03-01"
    assert tf.end is None


def test_malformed_output_is_no_filter() -> None:
    assert _parse_time_decision("not a pair at all") is None


def test_empty_content_is_no_filter() -> None:
    assert _parse_time_decision("") is None
    assert _parse_time_decision(None) is None


def test_unparseable_dates_are_no_filter() -> None:
    assert _parse_time_decision("updated (banana, None)") is None


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
    tf, prompt = _run_decision(history, "updated (2026-01-01, 2026-01-31)")
    assert all(isinstance(m, UserMessage) for m in prompt)
    text = prompt[-1].content
    assert "What changed last January?" in text
    assert "Let me look into that." not in text
    assert tf is not None and tf.start is not None and tf.end is not None


def test_no_user_turns_skips_the_llm() -> None:
    llm = MagicMock()
    history = [
        ChatMinimalTextMessage(
            message="assistant only", message_type=MessageType.ASSISTANT
        )
    ]
    assert decide_time_filter(history, llm) is None
    llm.invoke.assert_not_called()


def test_only_the_last_five_user_turns_reach_the_prompt() -> None:
    history = [
        ChatMinimalTextMessage(message=f"msg {i}", message_type=MessageType.USER)
        for i in range(8)
    ]
    _tf, prompt = _run_decision(history, "updated (None, None)")
    text = prompt[-1].content
    assert "msg 7" in text and "msg 3" in text
    assert "msg 2" not in text and "msg 0" not in text


# ---- Relative-token resolution (deterministic, fixed `now`) ----

# A Friday, mid-afternoon — exercises both week snapping and day flooring.
_NOW = datetime(2026, 7, 10, 13, 45, 22, tzinfo=timezone.utc)


def test_symmetric_week_token_is_the_previous_calendar_week() -> None:
    """ "(-P1W, -P1W)" means the previous ISO week (Monday-Sunday), not a
    single day one week ago."""
    tf = _parse_time_decision("updated (-P1W, -P1W)", now=_NOW)
    assert tf is not None
    assert tf.start is not None and tf.start.isoformat() == "2026-06-29T00:00:00+00:00"
    assert (
        tf.end is not None and tf.end.isoformat() == "2026-07-05T23:59:59.999999+00:00"
    )


def test_symmetric_day_token_is_that_full_day() -> None:
    tf = _parse_time_decision("created (-P1D, -P1D)", now=_NOW)
    assert tf is not None
    assert tf.field is DocumentTimeField.CREATED_AT
    assert tf.start is not None and tf.start.isoformat() == "2026-07-09T00:00:00+00:00"
    assert tf.end is not None and tf.end.date().isoformat() == "2026-07-09"


def test_symmetric_month_token_is_the_previous_calendar_month() -> None:
    tf = _parse_time_decision("updated (-P1M, -P1M)", now=_NOW)
    assert tf is not None
    assert tf.start is not None and tf.start.date().isoformat() == "2026-06-01"
    assert tf.end is not None and tf.end.date().isoformat() == "2026-06-30"


def test_symmetric_month_token_clamps_short_months() -> None:
    """From Mar 31, one month back lands in February and snaps to it."""
    end_of_march = datetime(2026, 3, 31, 12, 0, tzinfo=timezone.utc)
    tf = _parse_time_decision("updated (-P1M, -P1M)", now=end_of_march)
    assert tf is not None
    assert tf.start is not None and tf.start.date().isoformat() == "2026-02-01"
    assert tf.end is not None and tf.end.date().isoformat() == "2026-02-28"


def test_symmetric_year_token_is_the_previous_calendar_year() -> None:
    tf = _parse_time_decision("updated (-P1Y, -P1Y)", now=_NOW)
    assert tf is not None
    assert tf.start is not None and tf.start.date().isoformat() == "2025-01-01"
    assert tf.end is not None and tf.end.date().isoformat() == "2025-12-31"


def test_rolling_start_token_floors_to_its_day_not_its_period() -> None:
    """ "in the last 2 weeks" stays a rolling window: start is now minus 2 weeks
    floored to the start of that day — NOT snapped back to that week's Monday."""
    tf = _parse_time_decision("updated (-P2W, None)", now=_NOW)
    assert tf is not None
    assert tf.start is not None and tf.start.isoformat() == "2026-06-26T00:00:00+00:00"
    assert tf.end is None


def test_asymmetric_token_range_keeps_day_offsets() -> None:
    """ "10 to 15 weeks ago" is a numeric range, not a calendar period: each side
    resolves to its own day (floored / pushed to day end)."""
    tf = _parse_time_decision("updated (-P15W, -P10W)", now=_NOW)
    assert tf is not None
    assert tf.start is not None and tf.end is not None
    assert tf.start.date() == (_NOW - timedelta(weeks=15)).date()
    assert tf.start.isoformat().endswith("T00:00:00+00:00")
    assert tf.end.date() == (_NOW - timedelta(weeks=10)).date()


def test_upper_only_token_is_a_day_offset_not_a_period_end() -> None:
    """ "more than 20 weeks ago" must not widen to the end of that week."""
    tf = _parse_time_decision("updated (None, -P20W)", now=_NOW)
    assert tf is not None
    assert tf.start is None
    assert tf.end is not None and tf.end.date() == (_NOW - timedelta(weeks=20)).date()


# ---- TimeFilter.to_filter_ranges (intent -> named index ranges) ----


def test_created_intent_maps_to_single_created_range() -> None:
    tf = _parse_time_decision("created (2025-01-01, 2025-01-31)")
    assert tf is not None
    created_range, updated_range = tf.to_filter_ranges()
    assert updated_range is None
    assert created_range is not None
    assert created_range.start is not None and created_range.end is not None


def test_updated_intent_maps_to_overlap() -> None:
    """updated in [S, E] -> last_updated >= S AND created_at <= E (best-guess
    overlap), so a doc edited again after E is not dropped."""
    tf = _parse_time_decision("updated (2025-07-01, 2025-09-30)")
    assert tf is not None
    created_range, updated_range = tf.to_filter_ranges()
    assert updated_range is not None
    assert updated_range.start is not None and updated_range.end is None
    assert created_range is not None
    assert created_range.start is None and created_range.end is not None


def test_updated_lower_bound_only_has_no_created_clause() -> None:
    tf = _parse_time_decision("updated (2025-03-01, None)")
    assert tf is not None
    created_range, updated_range = tf.to_filter_ranges()
    assert created_range is None
    assert updated_range is not None and updated_range.start is not None
