"""The Slack built-in follows SLACK_API_URL end to end.

The provider points OAuth and its default egress at the configured cloud. The skill
helper gets that cloud through a rendered ``cloud.txt``, because it runs in the
sandbox without Onyx imports, and it refuses any host that is not a Slack cloud.
"""

from __future__ import annotations

import importlib
import importlib.util
from collections.abc import Callable, Iterator
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

import onyx.configs.slack_configs as slack_configs
import onyx.external_apps.providers.slack as slack_provider
from onyx.db.enums import ExternalAppType
from onyx.db.models import Skill
from onyx.skills.built_in import BUILT_IN_SKILLS
from onyx.skills.rendering import render_external_app_files

_SLACK_DIR = BUILT_IN_SKILLS["slack"].source_dir
Cloud = Callable[[str | None], ModuleType]


@pytest.fixture
def cloud(monkeypatch: pytest.MonkeyPatch) -> Iterator[Cloud]:
    """Reload the Slack config and provider for one SLACK_API_URL value."""

    def _set(raw: str | None) -> ModuleType:
        if raw is None:
            monkeypatch.delenv("SLACK_API_URL", raising=False)
        else:
            monkeypatch.setenv("SLACK_API_URL", raw)
        importlib.reload(slack_configs)
        return importlib.reload(slack_provider)

    yield _set
    monkeypatch.delenv("SLACK_API_URL", raising=False)
    importlib.reload(slack_configs)
    importlib.reload(slack_provider)


def _load_helper(cloud_txt: str | None, tmp_path: Path) -> ModuleType:
    """Import slack_api.py from a copy with ``cloud.txt`` beside it."""
    helper = tmp_path / "slack_api.py"
    helper.write_text((_SLACK_DIR / "slack_api.py").read_text())
    if cloud_txt is not None:
        (tmp_path / "cloud.txt").write_text(cloud_txt)
    spec = importlib.util.spec_from_file_location(f"slack_api_{uuid4().hex}", helper)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_govslack_provider_resolves_every_host(cloud: Cloud) -> None:
    provider_module = cloud("https://slack-gov.com/api/")
    provider = provider_module.SlackProvider()

    assert (
        provider.spec.oauth.authorize_url == "https://slack-gov.com/oauth/v2/authorize"
    )
    assert provider.spec.oauth.token_url == "https://slack-gov.com/api/oauth.v2.access"
    # The setup form pre-fills egress from the descriptor.
    assert provider.spec.descriptor.upstream_url_patterns == [
        "https://slack\\-gov\\.com/api/.*",
        "https://files\\.slack\\-gov\\.com/upload/v1/.*",
    ]
    assert provider.skill_template_values({}) == {
        "api_url": "https://slack-gov.com/api/",
        "files_host": "files.slack-gov.com",
    }
    assert "api.slack-gov.com/apps" in provider.spec.descriptor.setup_instructions


def test_commercial_provider_is_unchanged(cloud: Cloud) -> None:
    provider = cloud(None).SlackProvider()

    assert provider.spec.oauth.authorize_url == "https://slack.com/oauth/v2/authorize"
    assert provider.spec.descriptor.upstream_url_patterns == [
        "https://slack\\.com/api/.*",
        "https://files\\.slack\\.com/upload/v1/.*",
    ]


def test_rendered_cloud_file_names_the_configured_cloud(
    cloud: Cloud, monkeypatch: pytest.MonkeyPatch
) -> None:
    cloud("https://slack-gov.com/api/")

    class _App:
        id = 1
        app_type = ExternalAppType.SLACK
        organization_credentials = SimpleNamespace(get_value=lambda **_: {})

    monkeypatch.setattr(
        "onyx.skills.rendering.get_external_app_by_skill_id", lambda *_: _App()
    )
    monkeypatch.setattr(
        "onyx.skills.rendering.get_workspace_action_policies", lambda *_: {}
    )

    rendered = render_external_app_files(
        cast(Session, None),
        cast(Skill, SimpleNamespace(id=uuid4())),
        ExternalAppType.SLACK,
        _SLACK_DIR,
    )
    assert rendered["cloud.txt"].split() == [
        "https://slack-gov.com/api/",
        "files.slack-gov.com",
    ]
    assert not any(name.endswith(".template") for name in rendered)


def test_helper_reads_govslack_from_cloud_file(tmp_path: Path) -> None:
    helper = _load_helper("https://slack-gov.com/api/\nfiles.slack-gov.com\n", tmp_path)
    assert helper._BASE == "https://slack-gov.com/api/"
    assert helper._FILES_HOST == "files.slack-gov.com"


@pytest.mark.parametrize(
    "cloud_txt",
    [
        None,
        "",
        "(not configured — ask an admin to finish setting up this app)",
        "https://evil.example.com/api/\nfiles.evil.example.com\n",
        "https://slack-gov.com/api/\nfiles.slack.com\n",
    ],
)
def test_helper_falls_back_to_commercial_slack(
    cloud_txt: str | None, tmp_path: Path
) -> None:
    """A missing, unrendered, foreign or mixed cloud file never redirects the
    user's token."""
    helper = _load_helper(cloud_txt, tmp_path)
    assert helper._BASE == "https://slack.com/api/"
    assert helper._FILES_HOST == "files.slack.com"
