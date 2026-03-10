from onyx.prompts.constants import REMINDER_TAG_DESCRIPTION
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
