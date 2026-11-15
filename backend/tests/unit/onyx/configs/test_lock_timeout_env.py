"""Env-overridable lock TTLs: a positive override wins, unset is the default,
anything else warns and falls back."""

from __future__ import annotations

import logging

import pytest

from onyx.configs.constants import lock_timeout_from_env

NAME = "CELERY_TEST_LOCK_TIMEOUT"


def test_unset_uses_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(NAME, raising=False)
    assert lock_timeout_from_env(NAME, 3600) == 3600


def test_empty_uses_the_default_quietly(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Helm sends every unset value as an empty string."""
    monkeypatch.setenv(NAME, "")
    with caplog.at_level(logging.WARNING, logger="onyx.configs.constants"):
        assert lock_timeout_from_env(NAME, 3600) == 3600
    assert NAME not in caplog.text


def test_positive_override_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(NAME, "21600")
    assert lock_timeout_from_env(NAME, 3600) == 21600


@pytest.mark.parametrize("raw", ["0", "-5", "abc", "1.5"])
def test_bad_override_falls_back_loudly(
    raw: str, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv(NAME, raw)
    with caplog.at_level(logging.WARNING, logger="onyx.configs.constants"):
        assert lock_timeout_from_env(NAME, 3600) == 3600
    assert NAME in caplog.text
    assert "3600s default" in caplog.text


def test_override_under_the_minimum_falls_back_loudly(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A lock refreshed every 30 s must outlive that cadence."""
    monkeypatch.setenv(NAME, "20")
    with caplog.at_level(logging.WARNING, logger="onyx.configs.constants"):
        assert lock_timeout_from_env(NAME, 3600, minimum=120) == 3600
    assert "at least 120 seconds" in caplog.text
    monkeypatch.setenv(NAME, "120")
    assert lock_timeout_from_env(NAME, 3600, minimum=120) == 120
