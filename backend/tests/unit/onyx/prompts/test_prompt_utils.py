from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.prompts.chat_prompts import CITATION_GUIDANCE_REPLACEMENT_PAT
from onyx.prompts.chat_prompts import DATETIME_REPLACEMENT_PAT
from onyx.prompts.chat_prompts import REQUIRE_CITATION_GUIDANCE
from onyx.prompts.constants import REMINDER_TAG_DESCRIPTION
from onyx.prompts.prompt_utils import apply_prompt_placeholders
from onyx.prompts.prompt_utils import replace_current_datetime_tag
from onyx.prompts.prompt_utils import replace_reminder_tag


def test_replace_reminder_tag_pattern() -> None:
    prompt = "Some text {{REMINDER_TAG_DESCRIPTION}} more text"
    result = replace_reminder_tag(prompt)
    assert "{{REMINDER_TAG_DESCRIPTION}}" not in result
    assert REMINDER_TAG_DESCRIPTION in result


def test_replace_reminder_tag_no_pattern() -> None:
    prompt = "Some text without any pattern"
    result = replace_reminder_tag(prompt)
    assert result == prompt


@patch(
    "onyx.prompts.prompt_utils.get_current_llm_day_time",
    return_value="Wednesday July 15, 2026",
)
def test_replace_current_datetime_tag(mock_get_time: MagicMock) -> None:
    prompt = f"The current date is {DATETIME_REPLACEMENT_PAT}."
    result = replace_current_datetime_tag(prompt)
    assert result == "The current date is Wednesday July 15, 2026."
    mock_get_time.assert_called_once()


@patch(
    "onyx.prompts.prompt_utils.get_current_llm_day_time",
    return_value="Wednesday July 15, 2026",
)
def test_apply_prompt_placeholders_appends_datetime_when_aware(
    mock_get_time: MagicMock,
) -> None:
    prompt = "Custom agent instructions."
    result, should_append_citation = apply_prompt_placeholders(
        prompt,
        datetime_aware=True,
        append_datetime_if_aware=True,
    )
    assert "Wednesday July 15, 2026" in result
    assert should_append_citation is False
    mock_get_time.assert_called()


@patch(
    "onyx.prompts.prompt_utils.get_current_llm_day_time",
    return_value="Wednesday July 15, 2026",
)
def test_apply_prompt_placeholders_replaces_citation_guidance(
    _mock_get_time: MagicMock,
) -> None:
    prompt = f"Answer with citations. {CITATION_GUIDANCE_REPLACEMENT_PAT}"
    result, should_append_citation = apply_prompt_placeholders(
        prompt,
        should_cite_documents=True,
        append_citation_if_missing=False,
    )
    assert REQUIRE_CITATION_GUIDANCE in result
    assert CITATION_GUIDANCE_REPLACEMENT_PAT not in result
    assert should_append_citation is False
