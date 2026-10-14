"""Guards parsing of user-selectable reasoning-effort override values."""

import pytest

from onyx.llm.models import ReasoningEffort, parse_user_selectable_reasoning_effort


@pytest.mark.parametrize(
    ("value", "expected_effort"),
    [
        ("off", ReasoningEffort.OFF),
        ("low", ReasoningEffort.LOW),
        ("medium", ReasoningEffort.MEDIUM),
        ("high", ReasoningEffort.HIGH),
        ("xhigh", ReasoningEffort.XHIGH),
    ],
)
def test_parse_user_selectable_reasoning_effort_accepts_user_selectable_values(
    value: str,
    expected_effort: ReasoningEffort,
) -> None:
    assert parse_user_selectable_reasoning_effort(value) is expected_effort


def test_parse_user_selectable_reasoning_effort_rejects_auto() -> None:
    with pytest.raises(ValueError):
        parse_user_selectable_reasoning_effort("auto")


@pytest.mark.parametrize("value", ["ultra", ""])
def test_parse_user_selectable_reasoning_effort_rejects_unknown_values(
    value: str,
) -> None:
    with pytest.raises(ValueError):
        parse_user_selectable_reasoning_effort(value)
