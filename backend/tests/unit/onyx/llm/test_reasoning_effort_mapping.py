from onyx.llm.models import OPENAI_REASONING_EFFORT
from onyx.llm.models import ReasoningEffort


# Valid OpenAI reasoning effort values per the API documentation
# https://platform.openai.com/docs/api-reference/responses
VALID_OPENAI_REASONING_EFFORT_VALUES = frozenset(
    {"none", "minimal", "low", "medium", "high", "xhigh"}
)


def test_openai_reasoning_effort_mapping_has_valid_values() -> None:
    """Test that all OPENAI_REASONING_EFFORT mapping values are valid OpenAI API values.

    This test prevents regressions where invalid values like "auto" are passed to the
    OpenAI API, which would result in a 400 Bad Request error.

    The OpenAI API only accepts: 'none', 'minimal', 'low', 'medium', 'high', 'xhigh'
    """
    for effort_level, openai_value in OPENAI_REASONING_EFFORT.items():
        assert openai_value in VALID_OPENAI_REASONING_EFFORT_VALUES, (
            f"OPENAI_REASONING_EFFORT[{effort_level}] = '{openai_value}' is not a valid "
            f"OpenAI reasoning effort value. Valid values are: {sorted(VALID_OPENAI_REASONING_EFFORT_VALUES)}"
        )


def test_openai_reasoning_effort_mapping_covers_all_effort_levels() -> None:
    """Test that OPENAI_REASONING_EFFORT has mappings for all ReasoningEffort values.

    This ensures we don't accidentally forget to add a mapping when new effort levels are added.
    Note: ReasoningEffort.OFF maps to "none" in the OpenAI API.
    """
    # These are the effort levels that should have OpenAI mappings
    expected_effort_levels = {
        ReasoningEffort.AUTO,
        ReasoningEffort.OFF,
        ReasoningEffort.LOW,
        ReasoningEffort.MEDIUM,
        ReasoningEffort.HIGH,
    }

    mapped_effort_levels = set(OPENAI_REASONING_EFFORT.keys())

    assert mapped_effort_levels == expected_effort_levels, (
        f"OPENAI_REASONING_EFFORT mapping is missing or has extra effort levels. "
        f"Expected: {expected_effort_levels}, Got: {mapped_effort_levels}"
    )


def test_reasoning_effort_auto_does_not_map_to_auto() -> None:
    """Explicitly test that ReasoningEffort.AUTO does not map to the string 'auto'.

    OpenAI's API does not accept 'auto' as a value for reasoning.effort.
    This test exists as a specific guard against the bug that caused this test file
    to be created in the first place.
    """
    assert OPENAI_REASONING_EFFORT[ReasoningEffort.AUTO] != "auto", (
        "ReasoningEffort.AUTO must not map to 'auto' - OpenAI API rejects this value. "
        "Use a valid default like 'medium' or 'low' instead."
    )
