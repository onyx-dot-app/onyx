"""Unit tests for the mobile-OAuth app-redirect allowlist validator. Pure logic;
no external services."""

import pytest

from onyx.auth.users import validate_app_redirect
from onyx.error_handling.exceptions import OnyxError

ALLOW = ["onyx://"]


def test_allows_listed_scheme() -> None:
    assert validate_app_redirect("onyx://callback", ALLOW) == "onyx://callback"


def test_rejects_unlisted_scheme() -> None:
    with pytest.raises(OnyxError):
        validate_app_redirect("https://evil.example.com/steal", ALLOW)


def test_rejects_empty() -> None:
    with pytest.raises(OnyxError):
        validate_app_redirect("", ALLOW)


def test_rejects_when_allowlist_empty() -> None:
    with pytest.raises(OnyxError):
        validate_app_redirect("onyx://callback", [])
