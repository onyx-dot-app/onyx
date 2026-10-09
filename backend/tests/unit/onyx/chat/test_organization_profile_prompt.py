"""Guards the Organization Profile system-prompt block: it renders the resolved
directory fields when present and is absent when the profile is empty."""

from unittest.mock import patch

from onyx.chat.prompt_utils import build_system_prompt
from onyx.db.memory import UserInfo, UserMemoryContext


def _context(organization_profile: dict[str, str]) -> UserMemoryContext:
    return UserMemoryContext(
        user_info=UserInfo(
            name="User Example",
            email="user@example.com",
            organization_profile=organization_profile,
        ),
    )


def test_organization_profile_block_renders_fields() -> None:
    # get_company_context reads KV/cache. Patched so the test controls all inputs.
    with patch("onyx.chat.prompt_utils.get_company_context", return_value=None):
        prompt = build_system_prompt(
            "Base prompt.",
            user_memory_context=_context({"Country": "NL", "Department": "Legal"}),
        )
    assert "## Organization Profile" in prompt
    assert "- Country: NL" in prompt
    assert "- Department: Legal" in prompt


def test_organization_profile_block_absent_when_empty() -> None:
    with patch("onyx.chat.prompt_utils.get_company_context", return_value=None):
        prompt = build_system_prompt(
            "Base prompt.",
            user_memory_context=_context({}),
        )
    assert "## Organization Profile" not in prompt
