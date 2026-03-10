import pytest
from fastapi import HTTPException

import onyx.auth.users as users
from onyx.auth.users import verify_email_domain
from onyx.configs.constants import AuthType


def test_verify_email_domain_allows_case_insensitive_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Configure whitelist to lowercase while email has uppercase domain
    monkeypatch.setattr(users, "VALID_EMAIL_DOMAINS", ["example.com"], raising=False)

    # Should not raise
    verify_email_domain("User@EXAMPLE.COM")


def test_verify_email_domain_rejects_non_whitelisted_domain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(users, "VALID_EMAIL_DOMAINS", ["example.com"], raising=False)

    with pytest.raises(HTTPException) as exc:
        verify_email_domain("user@another.com")
    assert exc.value.status_code == 400
    assert "Email domain is not valid" in exc.value.detail


def test_verify_email_domain_invalid_email_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(users, "VALID_EMAIL_DOMAINS", ["example.com"], raising=False)

    with pytest.raises(HTTPException) as exc:
        verify_email_domain("userexample.com")  # missing '@'
    assert exc.value.status_code == 400
    assert "Email is not valid" in exc.value.detail


def test_verify_email_domain_rejects_plus_addressing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(users, "VALID_EMAIL_DOMAINS", [], raising=False)
    monkeypatch.setattr(users, "AUTH_TYPE", AuthType.CLOUD, raising=False)

    with pytest.raises(HTTPException) as exc:
        verify_email_domain("user+tag@gmail.com")
    assert exc.value.status_code == 400
    assert "'+'" in str(exc.value.detail)


def test_verify_email_domain_allows_plus_for_onyx_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(users, "VALID_EMAIL_DOMAINS", [], raising=False)
    monkeypatch.setattr(users, "AUTH_TYPE", AuthType.CLOUD, raising=False)

    # Should not raise for onyx.app domain
    verify_email_domain("user+tag@onyx.app")


def test_verify_email_domain_rejects_googlemail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(users, "VALID_EMAIL_DOMAINS", [], raising=False)
    monkeypatch.setattr(users, "AUTH_TYPE", AuthType.CLOUD, raising=False)

    with pytest.raises(HTTPException) as exc:
        verify_email_domain("user@googlemail.com")
    assert exc.value.status_code == 400
    assert "gmail.com" in str(exc.value.detail)
