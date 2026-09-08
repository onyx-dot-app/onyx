"""Guards the Language system-prompt block: present for a non-English UI language,
absent for English or no language, ordered before User Preferences, tolerant of an
unknown stored code, backed by an English name for every language the enum knows,
and appended to the deep research prompts that the user reads."""

from unittest.mock import patch

from onyx.chat.prompt_utils import (
    build_language_section,
    build_system_prompt,
    with_language_section,
)
from onyx.db.enums import SUPPORTED_LANGUAGE_ENGLISH_NAMES, SupportedLanguage
from onyx.db.memory import UserInfo, UserMemoryContext, supported_language_or_none
from onyx.prompts.deep_research.orchestration_layer import CLARIFICATION_PROMPT
from onyx.prompts.deep_research.research_agent import (
    RESEARCH_REPORT_PROMPT,
    USER_REPORT_QUERY,
)


def _prompt_for(
    language: SupportedLanguage | None, user_preferences: str | None = None
) -> str:
    context = UserMemoryContext(
        user_info=UserInfo(email="user@example.com", language=language),
        user_preferences=user_preferences,
    )
    # get_company_context reads the KV store. Patched so the test controls all inputs.
    with patch("onyx.chat.prompt_utils.get_company_context", return_value=None):
        return build_system_prompt("Base prompt.", user_memory_context=context)


def test_language_block_names_the_language_in_english() -> None:
    prompt = _prompt_for(SupportedLanguage.AR)
    assert "## Language" in prompt
    assert "The user's interface language is Arabic." in prompt
    assert "Reply in Arabic" in prompt


def test_english_prompt_is_identical_to_having_no_language() -> None:
    english_prompt = _prompt_for(SupportedLanguage.EN)
    assert "## Language" not in english_prompt
    assert english_prompt == _prompt_for(None)


def test_language_block_precedes_user_preferences() -> None:
    prompt = _prompt_for(SupportedLanguage.DE, user_preferences="Answer tersely.")
    assert prompt.index("## Language") < prompt.index("## User Preferences")


def test_unknown_stored_code_is_dropped_with_a_warning() -> None:
    with patch("onyx.db.memory.logger.warning") as warning:
        assert supported_language_or_none("xx") is None
    warning.assert_called_once_with(
        "Unknown user language %r, omitting the language hint", "xx"
    )
    assert supported_language_or_none("") is None
    assert supported_language_or_none("ar") is SupportedLanguage.AR


def test_every_supported_language_has_an_english_name() -> None:
    assert set(SUPPORTED_LANGUAGE_ENGLISH_NAMES) == set(SupportedLanguage)


def test_deep_research_prompt_gets_the_same_language_section() -> None:
    section = build_language_section(SupportedLanguage.JA)
    assert section is not None
    prompt = with_language_section(CLARIFICATION_PROMPT, section)
    assert prompt.startswith(CLARIFICATION_PROMPT)
    assert prompt.endswith(section)
    assert "interface language is Japanese" in prompt


def test_deep_research_prompts_defer_to_the_language_section() -> None:
    # Each user-facing deep research prompt yields to the appended section, so the
    # two never contradict each other for a user who types in another language.
    assert "interface language if one is given below" in CLARIFICATION_PROMPT
    assert "interface language if one is given below" in RESEARCH_REPORT_PROMPT
    assert "interface language if the system prompt names one" in USER_REPORT_QUERY


def test_deep_research_prompt_is_unchanged_without_a_language() -> None:
    assert build_language_section(SupportedLanguage.EN) is None
    assert with_language_section(CLARIFICATION_PROMPT, None) == CLARIFICATION_PROMPT
