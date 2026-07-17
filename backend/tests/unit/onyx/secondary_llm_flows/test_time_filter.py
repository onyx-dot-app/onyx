from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime
from datetime import timezone
from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.configs.constants import MessageType
from onyx.context.search.models import BaseFilters
from onyx.context.search.models import TimeRange
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


def test_lower_bound_only() -> None:
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


def test_partial_dates_fail_open() -> None:
    """A bare year or month name must not inherit today's month/day."""
    assert _parse_time_decision("updated (2022, None)") is None
    assert _parse_time_decision("updated (March, None)") is None


_NOW = datetime(2026, 7, 15, 13, 45, tzinfo=timezone.utc)


def test_end_at_today_is_treated_as_unbounded() -> None:
    """The model closing an open-ended time with end=today must not exclude
    documents updated later today."""
    tf = _parse_time_decision("updated (2026-07-01, 2026-07-15)", now=_NOW)
    assert tf is not None
    assert tf.start is not None
    assert tf.end is None


def test_future_bounds_are_dropped() -> None:
    assert _parse_time_decision("updated (2026-08-01, None)", now=_NOW) is None
    tf = _parse_time_decision("updated (2026-07-01, 2026-09-30)", now=_NOW)
    assert tf is not None
    assert tf.start is not None and tf.end is None


def test_today_window_keeps_its_start() -> None:
    """ "created today" keeps start=today; only the end is unbounded."""
    tf = _parse_time_decision("created (2026-07-15, 2026-07-15)", now=_NOW)
    assert tf is not None
    assert tf.start is not None and tf.start.date().isoformat() == "2026-07-15"
    assert tf.end is None


# ---- TimeFilter.apply_to (intersection with explicit filters) ----


def test_apply_to_sets_range_on_empty_filters() -> None:
    tf = _parse_time_decision("created (2025-01-01, 2025-01-31)")
    assert tf is not None
    filters = tf.apply_to(BaseFilters())
    assert filters.created_at_range is not None
    assert filters.updated_at_range is None


def test_apply_to_never_widens_an_explicit_range() -> None:
    explicit = BaseFilters(
        updated_at_range=TimeRange(
            start=datetime(2025, 6, 1, tzinfo=timezone.utc),
            end=datetime(2025, 6, 30, tzinfo=timezone.utc),
        )
    )
    tf = _parse_time_decision("updated (2025-01-01, None)")
    assert tf is not None
    filters = tf.apply_to(explicit)
    # The wider inferred window keeps the tighter explicit bounds.
    assert filters.updated_at_range is not None
    assert filters.updated_at_range.start == datetime(2025, 6, 1, tzinfo=timezone.utc)
    assert filters.updated_at_range.end == datetime(2025, 6, 30, tzinfo=timezone.utc)


def test_apply_to_drops_a_disjoint_inferred_window() -> None:
    """A conflicting inferred window must not silently match nothing."""
    explicit_range = TimeRange(
        start=datetime(2025, 6, 1, tzinfo=timezone.utc),
        end=datetime(2025, 6, 30, tzinfo=timezone.utc),
    )
    tf = _parse_time_decision("updated (2025-09-01, 2025-09-30)")
    assert tf is not None
    filters = tf.apply_to(BaseFilters(updated_at_range=explicit_range))
    assert filters.updated_at_range == explicit_range


def test_apply_to_narrows_an_explicit_range() -> None:
    explicit = BaseFilters(
        updated_at_range=TimeRange(start=datetime(2025, 1, 1, tzinfo=timezone.utc))
    )
    tf = _parse_time_decision("updated (2025-03-01, 2025-03-31)")
    assert tf is not None
    filters = tf.apply_to(explicit)
    assert filters.updated_at_range is not None
    assert filters.updated_at_range.start == datetime(2025, 3, 1, tzinfo=timezone.utc)
    assert filters.updated_at_range.end is not None


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
