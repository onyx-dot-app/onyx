import re
from pathlib import Path

import pytest

from onyx.server.features.build.sandbox.util import agent_instructions

_TEMPLATE_PLACEHOLDER_RE = re.compile(r"{{[A-Z0-9_]+}}")


def _template_path() -> Path:
    return Path(agent_instructions.__file__).parents[2] / "AGENTS.template.md"


def _unresolved_placeholders(content: str) -> set[str]:
    return set(_TEMPLATE_PLACEHOLDER_RE.findall(content))


def test_generate_agent_instructions_uses_configured_approval_timeouts_in_real_template(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        agent_instructions, "SANDBOX_APPROVAL_WAIT_TIMEOUT_SECONDS", 240
    )

    content = agent_instructions.generate_agent_instructions(
        template_path=_template_path(),
        skills_section="",
        connectable_apps_section="",
    )

    assert "240 seconds" in content
    assert "260 seconds" in content
    assert "3 minutes" not in content
    assert "200 seconds" not in content
    assert _unresolved_placeholders(content) == set()


def test_generate_agent_instructions_populates_real_template_runtime_values() -> None:
    skills_section = "- **company-search**: SENTINEL_SKILL_DESCRIPTION"

    content = agent_instructions.generate_agent_instructions(
        template_path=_template_path(),
        skills_section=skills_section,
        connectable_apps_section="",
        provider="openai",
        model_name="gpt-5-mini",
        nextjs_port=3210,
        disabled_tools=["web-search", "shell"],
        user_name="TEST_USER",
    )

    assert "TEST_USER" in content
    assert "3210" in content
    assert "OpenAI / gpt-5-mini" in content
    assert "web-search, shell" in content
    assert skills_section in content
    assert _unresolved_placeholders(content) == set()


def test_generate_agent_instructions_omits_optional_sections_when_values_absent() -> (
    None
):
    content = agent_instructions.generate_agent_instructions(
        template_path=_template_path(),
        skills_section="SENTINEL_NO_SKILLS",
        connectable_apps_section="",
    )

    assert "You are assisting **" not in content
    assert "**Disabled Tools**" not in content
    assert "SENTINEL_NO_SKILLS" in content
    assert _unresolved_placeholders(content) == set()


def test_build_connectable_apps_list_empty_renders_fallback() -> None:
    """No connectable apps → a fallback line, mirroring ``build_skills_section_
    from_data``'s "No skills available." (the template blurb stays either way)."""
    assert (
        agent_instructions.build_connectable_apps_list([])
        == "No connectable apps available."
    )


def test_generate_agent_instructions_keeps_connectable_blurb_when_empty() -> None:
    """No connectable apps → the static blurb still renders, list placeholder
    resolves to empty, nothing leaks through."""
    content = agent_instructions.generate_agent_instructions(
        template_path=_template_path(),
        skills_section="- **x**: y",
        connectable_apps_section="",
    )

    assert "## Connectable apps" in content  # blurb stays regardless of app count
    assert _unresolved_placeholders(content) == set()


def test_generate_agent_instructions_fills_connectable_list_from_template() -> None:
    """Connectable apps → template-owned blurb renders with the substituted list."""
    content = agent_instructions.generate_agent_instructions(
        template_path=_template_path(),
        skills_section="- **company-search**: SENTINEL_SKILL",
        connectable_apps_section="- **slack**: SENTINEL_CONNECTABLE",
    )

    assert "## Connectable apps" in content
    assert "- **company-search**: SENTINEL_SKILL" in content
    assert "- **slack**: SENTINEL_CONNECTABLE" in content
    assert _unresolved_placeholders(content) == set()
