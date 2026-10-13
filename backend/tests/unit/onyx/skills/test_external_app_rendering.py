"""``{{APP:<key>}}`` substitution in an external-app SKILL.md.

Most providers talk to a fixed host and need none of this. A provider hosted per
account (Zendesk) resolves the host from the admin's configuration, and the
rendered SKILL.md is how the agent learns which account it is talking to."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.db.enums import ExternalAppType
from onyx.db.models import Skill
from onyx.skills.built_in import BUILT_IN_SKILLS, BUILTIN_SKILLS_PATH
from onyx.skills.rendering import (
    render_external_app_skill,
    render_external_app_skill_for,
)

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


def test_the_push_and_preview_paths_render_the_same_markdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``render_external_app_skill_for`` is the one renderer both the sandbox
    push and the library preview call, so a user previewing a skill reads the
    connected account rather than the template's markers."""

    class _App:
        id = 1
        app_type = ExternalAppType.ZENDESK
        organization_credentials = SimpleNamespace(
            get_value=lambda **_: {"subdomain": "acme"}
        )

    monkeypatch.setattr(
        "onyx.skills.rendering.get_external_app_by_skill_id", lambda *_: _App()
    )
    monkeypatch.setattr("onyx.skills.rendering.get_action_policies", lambda *_: {})

    rendered = render_external_app_skill_for(
        cast(Session, None),
        cast(Skill, SimpleNamespace(id=uuid4())),
        ExternalAppType.ZENDESK,
        BUILT_IN_SKILLS["zendesk"].source_dir,
    )
    assert "https://acme.zendesk.com" in rendered
    assert "{{" not in rendered


def test_an_unresolvable_app_config_still_renders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rendering is a read-only projection of committed state: a provider that
    rejects the stored config leaves placeholders unconfigured rather than
    failing the push for every other skill in the fileset."""

    class _BrokenApp:
        id = 1
        app_type = ExternalAppType.ZENDESK
        organization_credentials = SimpleNamespace(
            get_value=lambda **_: {"subdomain": "not a subdomain"}
        )

    monkeypatch.setattr(
        "onyx.skills.rendering.get_external_app_by_skill_id", lambda *_: _BrokenApp()
    )
    monkeypatch.setattr("onyx.skills.rendering.get_action_policies", lambda *_: {})

    rendered = render_external_app_skill_for(
        cast(Session, None),
        cast(Skill, SimpleNamespace(id=uuid4())),
        ExternalAppType.ZENDESK,
        BUILT_IN_SKILLS["zendesk"].source_dir,
    )
    assert "not configured" in rendered
    assert "{{" not in rendered
