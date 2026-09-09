"""Guards the Language system-prompt block: one definitive line in every prompt,
naming the UI language when a non-English one is set and deferring to the message
otherwise, ordered before User Preferences, tolerant of an unknown stored code, backed
by an English name for every language the enum knows, and appended unchanged to the
deep research prompts that the user reads."""

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
from onyx.prompts.user_info import QUERY_LANGUAGE_PROMPT

FOLLOW_THE_MESSAGE = "Reply in the language the user writes in."


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
    assert "The user's interface language is Arabic. Reply in Arabic." in prompt
    assert "If the user explicitly asks for another language" in prompt
    assert FOLLOW_THE_MESSAGE not in prompt


def test_english_follows_the_message_like_no_language() -> None:
    english_prompt = _prompt_for(SupportedLanguage.EN)
    assert FOLLOW_THE_MESSAGE in english_prompt
    assert "interface language" not in english_prompt
    assert english_prompt == _prompt_for(None)


def test_prompt_without_user_context_still_gets_a_language_line() -> None:
    with patch("onyx.chat.prompt_utils.get_company_context", return_value=None):
        prompt = build_system_prompt("Base prompt.")
    assert prompt.count("## Language") == 1
    assert FOLLOW_THE_MESSAGE in prompt


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
    prompt = with_language_section(CLARIFICATION_PROMPT, section)
    assert prompt.startswith(CLARIFICATION_PROMPT)
    assert prompt.endswith(section)
    assert "interface language is Japanese. Reply in Japanese." in prompt


def test_deep_research_prompts_leave_the_language_to_the_section() -> None:
    # The appended section is the only language instruction, so the prompts no
    # longer ask the model to work out whether a language was given.
    for prompt in (CLARIFICATION_PROMPT, RESEARCH_REPORT_PROMPT, USER_REPORT_QUERY):
        assert "language" not in prompt.lower()
    assert build_language_section(None) == QUERY_LANGUAGE_PROMPT
    assert with_language_section(CLARIFICATION_PROMPT, QUERY_LANGUAGE_PROMPT).endswith(
        FOLLOW_THE_MESSAGE + "\n"
    )
