"""Guards parsing of stored chat-session reasoning-effort overrides."""

import pytest

from onyx.llm.models import ReasoningEffort, parse_reasoning_effort_override


def test_parse_reasoning_effort_override_none_defaults_to_auto() -> None:
    assert parse_reasoning_effort_override(None) is ReasoningEffort.AUTO


@pytest.mark.parametrize(
    ("stored_value", "expected_effort"),
    [
        ("off", ReasoningEffort.OFF),
        ("low", ReasoningEffort.LOW),
        ("medium", ReasoningEffort.MEDIUM),
        ("high", ReasoningEffort.HIGH),
        ("xhigh", ReasoningEffort.XHIGH),
    ],
)
def test_parse_reasoning_effort_override_accepts_user_selectable_values(
    stored_value: str,
    expected_effort: ReasoningEffort,
) -> None:
    assert parse_reasoning_effort_override(stored_value) is expected_effort


def test_parse_reasoning_effort_override_rejects_auto() -> None:
    with pytest.raises(ValueError):
        parse_reasoning_effort_override("auto")


@pytest.mark.parametrize("stored_value", ["ultra", ""])
def test_parse_reasoning_effort_override_rejects_unknown_values(
    stored_value: str,
) -> None:
    with pytest.raises(ValueError):
        parse_reasoning_effort_override(stored_value)
