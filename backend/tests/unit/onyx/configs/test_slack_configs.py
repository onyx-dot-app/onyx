"""SLACK_API_URL selects one Slack cloud for all of Onyx.

An unset or empty value is commercial Slack. A trusted cloud is normalized to
its domain. Anything else logs and falls back, so no Slack token goes to an
unknown host.
"""

from __future__ import annotations

import importlib
import logging
from collections.abc import Callable, Iterator
from types import ModuleType

import pytest

import onyx.configs.slack_configs as slack_configs

NAME = "SLACK_API_URL"
Reload = Callable[[str | None], ModuleType]


@pytest.fixture
def reload_with(monkeypatch: pytest.MonkeyPatch) -> Iterator[Reload]:
    """Reload slack_configs with SLACK_API_URL set, then restore the default."""

    def _reload(raw: str | None) -> ModuleType:
        if raw is None:
            monkeypatch.delenv(NAME, raising=False)
        else:
            monkeypatch.setenv(NAME, raw)
        return importlib.reload(slack_configs)

    yield _reload
    monkeypatch.delenv(NAME, raising=False)
    importlib.reload(slack_configs)


@pytest.mark.parametrize("raw", [None, "", "   "])
def test_unset_or_blank_is_commercial_slack(
    raw: str | None, reload_with: Reload
) -> None:
    """Helm sends every unset value as an empty string."""
    cfg = reload_with(raw)
    assert cfg.SLACK_DOMAIN == "slack.com"
    assert cfg.SLACK_API_URL == "https://slack.com/api/"


@pytest.mark.parametrize(
    "raw",
    [
        "https://slack-gov.com/api/",
        "https://slack-gov.com/api",
        "https://slack-gov.com",
        "  https://slack-gov.com/api/  ",
    ],
)
def test_govslack_derives_every_host(raw: str, reload_with: Reload) -> None:
    cfg = reload_with(raw)
    assert cfg.SLACK_DOMAIN == "slack-gov.com"
    assert cfg.SLACK_API_URL == "https://slack-gov.com/api/"
    assert cfg.SLACK_OAUTH_AUTHORIZE_URL == "https://slack-gov.com/oauth/v2/authorize"
    assert cfg.SLACK_OAUTH_ACCESS_URL == "https://slack-gov.com/api/oauth.v2.access"
    assert cfg.SLACK_FILES_HOST == "files.slack-gov.com"
    assert cfg.SLACK_APPS_URL == "https://api.slack-gov.com/apps"


@pytest.mark.parametrize(
    "raw",
    [
        "http://slack-gov.com/api/",
        "https://evil.example.com/api/",
        "https://slack-gov.com.evil.example.com/api/",
        "https://notslack-gov.com/api/",
        "slack-gov.com/api/",
    ],
)
def test_untrusted_value_falls_back_loudly(
    raw: str, reload_with: Reload, caplog: pytest.LogCaptureFixture
) -> None:
    """A Slack token must never be sent to a host outside the Slack clouds."""
    with caplog.at_level(logging.ERROR):
        cfg = reload_with(raw)
    assert cfg.SLACK_DOMAIN == "slack.com"
    assert "Ignoring SLACK_API_URL" in caplog.text


@pytest.mark.parametrize(
    ("netloc", "expected"),
    [
        ("slack-gov.com", True),
        ("acme.slack-gov.com", True),
        ("ACME.Slack-Gov.com", True),
        ("acme.slack-gov.com:443", True),
        ("files.slack-gov.com", True),
        ("slack.com", False),
        ("notslack-gov.com", False),
        ("slack-gov.com.evil.example.com", False),
        ("user@acme.slack-gov.com", True),
    ],
)
def test_is_slack_host_matches_the_configured_cloud(
    netloc: str, expected: bool, reload_with: Reload
) -> None:
    cfg = reload_with("https://slack-gov.com/api/")
    assert cfg.is_slack_host(netloc) is expected


def test_egress_patterns_escape_the_domain(reload_with: Reload) -> None:
    cfg = reload_with("https://slack-gov.com/api/")
    assert cfg.slack_url_pattern("/api/.*") == "https://slack\\-gov\\.com/api/.*"
    assert (
        cfg.slack_files_url_pattern("/upload/v1/.*")
        == "https://files\\.slack\\-gov\\.com/upload/v1/.*"
    )
