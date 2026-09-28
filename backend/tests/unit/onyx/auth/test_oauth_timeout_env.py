"""`_timeout_from_env` must never yield a value that removes the timeout."""

import pytest

from onyx.auth.oauth_refresher import _timeout_from_env

VAR = "ONYX_TEST_OAUTH_TIMEOUT"
DEFAULT = 15.0


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, DEFAULT),  # unset
        ("", DEFAULT),  # set but empty
        ("30", 30.0),
        ("0.5", 0.5),
        ("inf", DEFAULT),  # would disable the bound
        ("-inf", DEFAULT),
        ("nan", DEFAULT),
        ("0", DEFAULT),  # would abort every refresh immediately
        ("-5", DEFAULT),
        ("abc", DEFAULT),
    ],
)
def test_timeout_from_env(
    monkeypatch: pytest.MonkeyPatch, raw: str | None, expected: float
) -> None:
    if raw is None:
        monkeypatch.delenv(VAR, raising=False)
    else:
        monkeypatch.setenv(VAR, raw)
    assert _timeout_from_env(VAR, DEFAULT) == expected
