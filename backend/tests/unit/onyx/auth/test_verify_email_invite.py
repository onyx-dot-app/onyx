import pytest

import onyx.auth.users as users
from onyx.auth.users import verify_email_is_invited
from onyx.error_handling.exceptions import OnyxError


def test_verify_email_is_invited_enforced_for_basic_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(users, "workspace_invite_only_enabled", lambda: True)
    monkeypatch.setattr(
        users,
        "get_invited_users",
        lambda: ["allowed@example.com"],
        raising=False,
    )

    with pytest.raises(OnyxError) as exc:
        verify_email_is_invited("newuser@example.com")
    assert exc.value.status_code == 403


def test_verify_email_is_invited_skipped_when_invite_only_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(users, "workspace_invite_only_enabled", lambda: False)
    monkeypatch.setattr(
        users,
        "get_invited_users",
        lambda: ["allowed@example.com"],
        raising=False,
    )

    verify_email_is_invited("newuser@example.com")


def test_sso_managed_bypasses_whitelist_under_basic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider-row login on a BASIC deployment is IdP-managed, so the
    workspace invite list must not block its JIT-provisioned users."""
    monkeypatch.setattr(users, "workspace_invite_only_enabled", lambda: True)
    monkeypatch.setattr(
        users,
        "get_invited_users",
        lambda: ["allowed@example.com"],
        raising=False,
    )

    verify_email_is_invited("newuser@example.com", sso_managed=True)


def test_sso_managed_default_false_keeps_enforcement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Callers that do not declare SSO provenance keep the invite check."""
    monkeypatch.setattr(users, "workspace_invite_only_enabled", lambda: True)
    monkeypatch.setattr(
        users,
        "get_invited_users",
        lambda: ["allowed@example.com"],
        raising=False,
    )

    with pytest.raises(OnyxError):
        verify_email_is_invited("newuser@example.com", sso_managed=False)
