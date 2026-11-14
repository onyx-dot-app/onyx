"""GOOGLE_API_ENDPOINT_OVERRIDE sends tokens and credentials to its URL, so
plain HTTP is accepted only for an endpoint on this machine."""

import pytest

from onyx.configs.app_configs import _load_google_api_endpoint_override


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("", None),
        ("http://localhost:9650", "http://localhost:9650/"),
        ("http://127.0.0.1:9650/", "http://127.0.0.1:9650/"),
        ("http://[::1]:9650", "http://[::1]:9650/"),
        ("https://mock.example.com", "https://mock.example.com/"),
        ("http://mock.example.com", None),
        ("http://10.0.0.5:9650", None),
        ("ftp://localhost", None),
        ("not a url", None),
    ],
)
def test_override_needs_https_off_this_machine(
    monkeypatch: pytest.MonkeyPatch, raw: str, expected: str | None
) -> None:
    monkeypatch.setenv("GOOGLE_API_ENDPOINT_OVERRIDE", raw)

    assert _load_google_api_endpoint_override() == expected
