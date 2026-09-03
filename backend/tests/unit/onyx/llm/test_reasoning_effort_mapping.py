from onyx.llm.models import OPENAI_REASONING_EFFORT, ReasoningEffort

# Valid OpenAI reasoning effort values per the API documentation
# https://platform.openai.com/docs/api-reference/responses
VALID_OPENAI_REASONING_EFFORT_VALUES = frozenset(
    {"none", "minimal", "low", "medium", "high", "xhigh"}
)


def test_openai_reasoning_effort_mapping_has_valid_values() -> None:
    """Every mapped value must be one the OpenAI API accepts, or the request 400s.

    The OpenAI API only accepts: 'none', 'minimal', 'low', 'medium', 'high', 'xhigh'
    """
    for effort_level, openai_value in OPENAI_REASONING_EFFORT.items():
        assert openai_value in VALID_OPENAI_REASONING_EFFORT_VALUES, (
            f"OPENAI_REASONING_EFFORT[{effort_level}] = '{openai_value}' is not a valid "
            f"OpenAI reasoning effort value. Valid values are: {sorted(VALID_OPENAI_REASONING_EFFORT_VALUES)}"
        )


def test_openai_reasoning_effort_mapping_covers_all_effort_levels() -> None:
    """A new effort level must get an OpenAI mapping in the same change."""
    assert set(OPENAI_REASONING_EFFORT) == set(ReasoningEffort)
