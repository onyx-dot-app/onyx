from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.prompts.chat_prompts import CITATION_GUIDANCE_REPLACEMENT_PAT
from onyx.prompts.chat_prompts import DATETIME_REPLACEMENT_PAT
from onyx.prompts.chat_prompts import REQUIRE_CITATION_GUIDANCE
from onyx.prompts.constants import REMINDER_TAG_DESCRIPTION
from onyx.prompts.prompt_utils import apply_prompt_placeholders
from onyx.prompts.prompt_utils import replace_current_datetime_tag
from onyx.prompts.prompt_utils import replace_reminder_tag
from onyx.prompts.prompt_utils import substitute_user_placeholders


def test_replace_reminder_tag_pattern() -> None:
    prompt = "Some text {{REMINDER_TAG_DESCRIPTION}} more text"
    result = replace_reminder_tag(prompt)
    assert "{{REMINDER_TAG_DESCRIPTION}}" not in result
    assert REMINDER_TAG_DESCRIPTION in result


def test_replace_reminder_tag_no_pattern() -> None:
    prompt = "Some text without any pattern"
    result = replace_reminder_tag(prompt)
    assert result == prompt


# --- {{user.<key>}} placeholder substitution ---

_VALUES = {
    "department": "Engineering",
    "city": "Berlin",
    "email": "a@example.com",
}


def test_substitute_known_key_is_replaced_with_value() -> None:
    assert (
        substitute_user_placeholders("Dept: {{user.department}}", _VALUES)
        == "Dept: Engineering"
    )


def test_substitute_tolerates_inner_whitespace() -> None:
    assert (
        substitute_user_placeholders("City: {{ user.city }}", _VALUES) == "City: Berlin"
    )


def test_substitute_known_key_without_value_becomes_empty() -> None:
    # `state` is a recognized key but the user has no captured value for it.
    assert substitute_user_placeholders("State=[{{user.state}}]", _VALUES) == "State=[]"


def test_substitute_unknown_key_is_left_literal() -> None:
    # A typo / unrecognized key must survive so the author notices it.
    text = "Typo: {{user.deparment}}"
    assert substitute_user_placeholders(text, _VALUES) == text


def test_substitute_leaves_literal_braces_untouched() -> None:
    # User prompts routinely contain literal braces (JSON/code/LaTeX); they must
    # never be treated as placeholders and must never raise.
    text = 'Return JSON like {"a": 1, "nested": {"b": 2}} and \\frac{x}{y}.'
    assert substitute_user_placeholders(text, _VALUES) == text


def test_substitute_multiple_placeholders_in_one_string() -> None:
    result = substitute_user_placeholders(
        "{{user.department}} in {{user.city}} <{{user.email}}>", _VALUES
    )
    assert result == "Engineering in Berlin <a@example.com>"


def test_substitute_non_entra_user_empties_all_known_keys() -> None:
    # Empty value map (user never logged in via Entra): known keys resolve to ""
    # (no raw leak), unknown keys stay literal.
    text = "D={{user.department}} X={{user.bogus}}"
    assert substitute_user_placeholders(text, {}) == "D= X={{user.bogus}}"


def test_substitute_ignores_non_user_namespace() -> None:
    # Only the `user.` namespace is handled; other double-brace tags are left
    # alone for their own handlers (e.g. {{CURRENT_DATETIME}}).
    text = "Now: {{CURRENT_DATETIME}} and {{user.city}}"
    assert (
        substitute_user_placeholders(text, _VALUES)
        == "Now: {{CURRENT_DATETIME}} and Berlin"
    )


def test_frontend_placeholder_catalog_matches_backend_allowlist() -> None:
    """The UI catalog (userPlaceholders.ts) must offer exactly the keys the
    backend recognizes — a drifted catalog either hides usable placeholders or
    offers ones that silently resolve to ''."""
    import re
    from pathlib import Path

    from onyx.prompts.prompt_utils import USER_PLACEHOLDER_KEYS

    ts_path = (
        Path(__file__).parents[5]
        / "web"
        / "src"
        / "lib"
        / "agents"
        / "userPlaceholders.ts"
    )
    if not ts_path.exists():  # backend-only checkouts
        import pytest

        pytest.skip("web/ not present in this checkout")
    frontend_keys = set(re.findall(r'key: "([a-z_]+)"', ts_path.read_text()))
    assert frontend_keys == set(USER_PLACEHOLDER_KEYS)


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
