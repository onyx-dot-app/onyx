import pytest

from onyx.chat import prompt_utils
from onyx.chat.prompt_utils import _build_user_information_section
from onyx.db.memory import UserInfo
from onyx.db.memory import UserMemoryContext


def _sample_context() -> UserMemoryContext:
    return UserMemoryContext(
        user_info=UserInfo(
            name="John Doe",
            email="john@example.com",
            role="Engineer",
        ),
        user_preferences="Prefers concise answers",
        memories=("Works on the billing service", "Based in Berlin"),
    )


def test_user_information_includes_pii_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Default behaviour: the basic-info sub-block (name/email/role) is rendered.
    monkeypatch.setattr(prompt_utils, "DISABLE_USER_IDENTITY_IN_PROMPT", False)

    result = _build_user_information_section(_sample_context(), company_context=None)

    assert "## Basic Information" in result
    assert "John Doe" in result
    assert "john@example.com" in result
    assert "Engineer" in result
    # Preferences and memories are still present.
    assert "Prefers concise answers" in result
    assert "Works on the billing service" in result


def test_user_information_omits_pii_when_flag_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # With the flag on, name/email/role must not leak into the prompt, but
    # preferences and memories must still be available to the model.
    monkeypatch.setattr(prompt_utils, "DISABLE_USER_IDENTITY_IN_PROMPT", True)

    result = _build_user_information_section(_sample_context(), company_context=None)

    assert "## Basic Information" not in result
    assert "John Doe" not in result
    assert "john@example.com" not in result
    # Non-identifying context is preserved.
    assert "Prefers concise answers" in result
    assert "Works on the billing service" in result
    assert "Based in Berlin" in result


def test_team_information_unaffected_by_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The flag only gates the user's own identity, never the team/company block.
    monkeypatch.setattr(prompt_utils, "DISABLE_USER_IDENTITY_IN_PROMPT", True)

    result = _build_user_information_section(
        _sample_context(), company_context="Acme Corp builds rockets"
    )

    assert "## Team Information" in result
    assert "Acme Corp builds rockets" in result
    assert "John Doe" not in result
