"""``{{APP:<key>}}`` substitution in an external-app SKILL.md — how a
per-account provider (Zendesk) tells the agent which account it is on."""

from __future__ import annotations

from collections.abc import Mapping
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.db.enums import ExternalAppType
from onyx.db.models import Skill
from onyx.external_apps.providers.zendesk import ZendeskProvider
from onyx.skills.built_in import BUILT_IN_SKILLS, BUILTIN_SKILLS_PATH
from onyx.skills.rendering import (
    render_external_app_files,
    render_external_app_skill,
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
    """A half-configured app still pushes, saying it needs setting up."""
    rendered = render_external_app_skill(_TEMPLATE, ExternalAppType.ZENDESK, {}, {})
    assert "{{" not in rendered
    assert "not configured" in rendered


def test_blank_value_is_treated_as_unconfigured() -> None:
    rendered = render_external_app_skill(
        _TEMPLATE, ExternalAppType.ZENDESK, {}, {"base_url": ""}
    )
    assert "not configured" in rendered


def test_zendesk_skill_renders_with_the_configured_account() -> None:
    """The shipped template resolves end to end; a surviving marker raises."""
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
    """One renderer for both push and preview, so a user previewing a skill
    reads the connected account rather than the template's markers."""

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

    rendered = render_external_app_files(
        cast(Session, None),
        cast(Skill, SimpleNamespace(id=uuid4())),
        ExternalAppType.ZENDESK,
        BUILT_IN_SKILLS["zendesk"].source_dir,
    )
    assert "https://acme.zendesk.com" in rendered["SKILL.md"]
    assert "{{" not in rendered["SKILL.md"]


def test_an_unresolvable_app_config_still_renders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A rejected config leaves placeholders unconfigured rather than failing
    the push for every other skill in the fileset."""

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

    rendered = render_external_app_files(
        cast(Session, None),
        cast(Skill, SimpleNamespace(id=uuid4())),
        ExternalAppType.ZENDESK,
        BUILT_IN_SKILLS["zendesk"].source_dir,
    )
    assert "not configured" in rendered["SKILL.md"]
    assert "{{" not in rendered["SKILL.md"]


def test_a_helper_template_is_rendered_beside_the_skill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bundled helper gets the connected account baked in, so no command it
    offers takes an account it could only be given one value for."""

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

    rendered = render_external_app_files(
        cast(Session, None),
        cast(Skill, SimpleNamespace(id=uuid4())),
        ExternalAppType.ZENDESK,
        BUILT_IN_SKILLS["zendesk"].source_dir,
    )
    assert rendered["account.txt"].strip() == "https://acme.zendesk.com"
    assert "SKILL.md" in rendered
    # The raw templates never ship; only their rendered names do.
    assert not any(name.endswith(".template") for name in rendered)


def test_rendered_files_withhold_secret_credential_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, str] = {}

    def capture_values(
        _self: ZendeskProvider, credentials: Mapping[str, str]
    ) -> dict[str, str]:
        captured.update(credentials)
        return {}

    app = SimpleNamespace(
        id=1,
        app_type=ExternalAppType.ZENDESK,
        organization_credentials=SimpleNamespace(
            get_value=lambda **_: {
                "subdomain": "acme",
                "client_id": "cid",
                "client_secret": "secret",
            }
        ),
    )
    monkeypatch.setattr(
        "onyx.skills.rendering.get_external_app_by_skill_id", lambda *_: app
    )
    monkeypatch.setattr("onyx.skills.rendering.get_action_policies", lambda *_: {})
    monkeypatch.setattr(ZendeskProvider, "skill_template_values", capture_values)
    rendered = render_external_app_files(
        cast(Session, None),
        cast(Skill, SimpleNamespace(id=uuid4())),
        ExternalAppType.ZENDESK,
        BUILT_IN_SKILLS["zendesk"].source_dir,
    )
    assert captured == {"subdomain": "acme", "client_id": "cid"}
    assert all("secret" not in content for content in rendered.values())
