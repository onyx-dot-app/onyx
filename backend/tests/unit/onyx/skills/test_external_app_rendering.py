"""``{{APP:<key>}}`` substitution in an external-app SKILL.md — how a
per-account provider (Zendesk) tells the agent which account it is on."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.db.enums import ExternalAppType
from onyx.db.models import Skill
from onyx.external_apps.providers.zendesk import ZendeskProvider
from onyx.skills.built_in import (
    BUILT_IN_SKILLS,
    BUILTIN_SKILLS_PATH,
    BuiltInSkillDefinition,
)
from onyx.skills.push import _add_static_builtin
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


def test_file_renderer_substitutes_the_configured_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The file renderer resolves account markers in the skill instructions."""

    class _App:
        id = 1
        app_type = ExternalAppType.ZENDESK
        organization_credentials = SimpleNamespace(
            get_value=lambda **_: {"subdomain": "acme"}
        )

    monkeypatch.setattr(
        "onyx.skills.rendering.get_external_app_by_skill_id", lambda *_: _App()
    )
    monkeypatch.setattr(
        "onyx.skills.rendering.get_workspace_action_policies", lambda *_: {}
    )

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
    monkeypatch.setattr(
        "onyx.skills.rendering.get_workspace_action_policies", lambda *_: {}
    )

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
    monkeypatch.setattr(
        "onyx.skills.rendering.get_workspace_action_policies", lambda *_: {}
    )

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


def test_static_and_rendered_files_share_source_exclusions(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "zendesk"
    source_dir.mkdir()
    sources = {
        "SKILL.md.template": _TEMPLATE,
        "account.txt.template": "{{APP:base_url}}",
        "helper.py": "print('ready')",
        ".private/hidden.txt.template": "hidden",
        "__pycache__/cached.txt.template": "cached",
        ".hidden.template": "hidden",
        ".private/hidden.py": "hidden",
        "__pycache__/cached.py": "cached",
        "directory.template/visible.txt.template": "visible",
    }
    for name, content in sources.items():
        path = source_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    monkeypatch.setattr("onyx.skills.built_in.BUILTIN_SKILLS_PATH", tmp_path)
    monkeypatch.setattr(
        "onyx.skills.rendering.get_external_app_by_skill_id", lambda *_: None
    )
    skill = cast(Skill, SimpleNamespace(id=uuid4(), name="zendesk"))
    definition = BuiltInSkillDefinition(built_in_skill_id="zendesk")

    static: dict[str, bytes] = {}
    _add_static_builtin(static, skill, definition)
    assert static == {"zendesk/helper.py": b"print('ready')"}

    rendered = render_external_app_files(
        cast(Session, None), skill, ExternalAppType.ZENDESK, definition.source_dir
    )
    assert set(rendered) == {
        "SKILL.md",
        "account.txt",
        "directory.template/visible.txt",
    }
    assert rendered["directory.template/visible.txt"] == "visible"


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
                "client_secret": "test-client-secret-do-not-render",
            }
        ),
    )
    monkeypatch.setattr(
        "onyx.skills.rendering.get_external_app_by_skill_id", lambda *_: app
    )
    monkeypatch.setattr(
        "onyx.skills.rendering.get_workspace_action_policies", lambda *_: {}
    )
    monkeypatch.setattr(ZendeskProvider, "skill_template_values", capture_values)
    rendered = render_external_app_files(
        cast(Session, None),
        cast(Skill, SimpleNamespace(id=uuid4())),
        ExternalAppType.ZENDESK,
        BUILT_IN_SKILLS["zendesk"].source_dir,
    )
    assert captured == {"subdomain": "acme", "client_id": "cid"}
    assert all(
        "test-client-secret-do-not-render" not in content
        for content in rendered.values()
    )
