import pytest

from shared_configs.configs import _int_env_or_default


def test_unset_and_empty_values_use_the_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SOME_LIMIT", raising=False)
    assert _int_env_or_default("SOME_LIMIT", 16) == 16
    monkeypatch.setenv("SOME_LIMIT", "")
    assert _int_env_or_default("SOME_LIMIT", 16) == 16


def test_integer_value_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOME_LIMIT", "64")
    assert _int_env_or_default("SOME_LIMIT", 16) == 64


def test_bad_value_is_logged_and_uses_the_default(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("SOME_LIMIT", "many")
    assert _int_env_or_default("SOME_LIMIT", 16) == 16
    assert "SOME_LIMIT='many' is not an integer" in caplog.text
