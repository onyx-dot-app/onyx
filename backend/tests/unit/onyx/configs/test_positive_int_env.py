"""Env-overridable positive integers: unset is the default, invalid is None."""

from __future__ import annotations

import logging

import pytest

from onyx.configs.constants import positive_int_from_env

NAME = "ONYX_TEST_POSITIVE_INT"


@pytest.mark.parametrize("raw", [None, ""])
def test_unset_or_empty_uses_the_default(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, raw: str | None
) -> None:
    if raw is None:
        monkeypatch.delenv(NAME, raising=False)
    else:
        monkeypatch.setenv(NAME, raw)
    with caplog.at_level(logging.ERROR, logger="onyx.configs.constants"):
        assert positive_int_from_env(NAME, 500) == 500
    assert NAME not in caplog.text


def test_positive_override_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(NAME, "42")
    assert positive_int_from_env(NAME, 500) == 42


@pytest.mark.parametrize("raw", ["abc", "1.5", "0", "-3"])
def test_invalid_value_logs_and_returns_none(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, raw: str
) -> None:
    monkeypatch.setenv(NAME, raw)
    with caplog.at_level(logging.ERROR, logger="onyx.configs.constants"):
        assert positive_int_from_env(NAME, 500) is None
    assert NAME in caplog.text
