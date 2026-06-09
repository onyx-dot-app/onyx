import pytest

import onyx.auth.users as users
from onyx.auth.users import verify_email_domain
from onyx.configs.constants import AuthType
from onyx.error_handling.exceptions import OnyxError


def test_verify_email_domain_allows_case_insensitive_match() -> None:
    # Configure whitelist to lowercase while email has uppercase domain
    verify_email_domain("User@EXAMPLE.COM", valid_email_domains=["example.com"])


def test_verify_email_domain_rejects_non_whitelisted_domain() -> None:
    with pytest.raises(OnyxError) as exc:
        verify_email_domain("user@another.com", valid_email_domains=["example.com"])
    assert exc.value.status_code == 400
    assert "Email domain is not valid" in exc.value.detail


def test_verify_email_domain_invalid_email_format() -> None:
    with pytest.raises(OnyxError) as exc:
        verify_email_domain("userexample.com", valid_email_domains=["example.com"])
    assert exc.value.status_code == 400
    assert "Email is not valid" in exc.value.detail


def test_verify_email_domain_rejects_plus_addressing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(users, "AUTH_TYPE", AuthType.CLOUD, raising=False)

    with pytest.raises(OnyxError) as exc:
        verify_email_domain("user+tag@gmail.com", valid_email_domains=[])
    assert exc.value.status_code == 400
    assert "'+'" in exc.value.detail


def test_verify_email_domain_allows_plus_for_onyx_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(users, "AUTH_TYPE", AuthType.CLOUD, raising=False)

    # Should not raise for onyx.app domain
    verify_email_domain("user+tag@onyx.app", valid_email_domains=[])


def test_verify_email_domain_rejects_dotted_gmail_on_registration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(users, "AUTH_TYPE", AuthType.CLOUD, raising=False)

    with pytest.raises(OnyxError) as exc:
        verify_email_domain(
            "first.last@gmail.com",
            valid_email_domains=[],
            is_registration=True,
        )
    assert exc.value.status_code == 400
    assert "'.'" in exc.value.detail


def test_verify_email_domain_dotted_gmail_allowed_when_not_registration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(users, "AUTH_TYPE", AuthType.CLOUD, raising=False)

    # Existing user signing in — should not be blocked
    verify_email_domain(
        "first.last@gmail.com", valid_email_domains=[], is_registration=False
    )


def test_verify_email_domain_allows_dotted_non_gmail_on_registration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(users, "AUTH_TYPE", AuthType.CLOUD, raising=False)

    verify_email_domain(
        "first.last@example.com",
        valid_email_domains=[],
        is_registration=True,
    )


def test_verify_email_domain_dotted_gmail_allowed_when_not_cloud(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(users, "AUTH_TYPE", AuthType.BASIC, raising=False)

    verify_email_domain(
        "first.last@gmail.com",
        valid_email_domains=[],
        is_registration=True,
    )


def test_verify_email_domain_rejects_googlemail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(users, "AUTH_TYPE", AuthType.CLOUD, raising=False)

    with pytest.raises(OnyxError) as exc:
        verify_email_domain("user@googlemail.com", valid_email_domains=[])
    assert exc.value.status_code == 400
    assert "gmail.com" in exc.value.detail
