"""``{{APP:<key>}}`` substitution in an external-app SKILL.md.

Most providers talk to a fixed host and need none of this. A provider hosted per
account (Zendesk) resolves the host from the admin's configuration, and the
rendered SKILL.md is how the agent learns which account it is talking to."""

from __future__ import annotations

from onyx.db.enums import ExternalAppType
from onyx.skills.built_in import BUILTIN_SKILLS_PATH
from onyx.skills.rendering import render_external_app_skill

_TEMPLATE = "---\nname: x\ndescription: d\n---\n\nbase: {{APP:base_url}}\n"


def test_app_values_are_substituted() -> None:
    rendered = render_external_app_skill(
        _TEMPLATE,
        ExternalAppType.ZENDESK,
        {},
        {"base_url": "https://acme.zendesk.com"},
    )
    assert "base: https://acme.zendesk.com" in rendered


def test_unknown_key_renders_as_unconfigured_rather_than_failing() -> None:
    """A half-configured app still pushes: the agent reads that the app needs
    setting up instead of the whole fileset failing to render."""
    rendered = render_external_app_skill(_TEMPLATE, ExternalAppType.ZENDESK, {}, {})
    assert "{{" not in rendered
    assert "not configured" in rendered


def test_blank_value_is_treated_as_unconfigured() -> None:
    rendered = render_external_app_skill(
        _TEMPLATE, ExternalAppType.ZENDESK, {}, {"base_url": ""}
    )
    assert "not configured" in rendered


def test_zendesk_skill_renders_with_the_configured_account() -> None:
    """The shipped template resolves end to end — no marker survives the render
    (``render_external_app_skill`` raises on one that does)."""
    template = (BUILTIN_SKILLS_PATH / "zendesk" / "SKILL.md.template").read_text()
    rendered = render_external_app_skill(
        template,
        ExternalAppType.ZENDESK,
        {},
        {"base_url": "https://acme.zendesk.com"},
    )
    assert "https://acme.zendesk.com" in rendered
