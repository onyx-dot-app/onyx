"""SLACK_API_URL: unset or empty is commercial Slack, a trusted host is
normalized to its /api/ base, and anything else logs and falls back."""

from __future__ import annotations

import logging

import pytest

from onyx.configs.onyxbot_configs import _load_slack_api_url

NAME = "SLACK_API_URL"
COMMERCIAL = "https://slack.com/api/"
GOVSLACK = "https://slack-gov.com/api/"


@pytest.mark.parametrize("raw", [None, "", "   "])
def test_unset_or_blank_is_commercial_slack(
    raw: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Helm sends every unset value as an empty string."""
    if raw is None:
        monkeypatch.delenv(NAME, raising=False)
    else:
        monkeypatch.setenv(NAME, raw)
    assert _load_slack_api_url() == COMMERCIAL


@pytest.mark.parametrize(
    "raw",
    [
        "https://slack-gov.com/api/",
        "https://slack-gov.com/api",
        "https://slack-gov.com",
        "  https://slack-gov.com/api/  ",
    ],
)
def test_govslack_is_normalized(raw: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(NAME, raw)
    assert _load_slack_api_url() == GOVSLACK


def test_commercial_override_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(NAME, "https://slack.com/api/")
    assert _load_slack_api_url() == COMMERCIAL


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
    raw: str, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A bot token must never be sent to a host outside the Slack clouds."""
    monkeypatch.setenv(NAME, raw)
    with caplog.at_level(logging.ERROR):
        assert _load_slack_api_url() == COMMERCIAL
    assert "Ignoring SLACK_API_URL" in caplog.text
