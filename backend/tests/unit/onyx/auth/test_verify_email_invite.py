import pytest

import onyx.auth.users as users
from onyx.auth.users import verify_email_is_invited
from onyx.configs.constants import AuthType
from onyx.error_handling.exceptions import OnyxError


@pytest.mark.parametrize("auth_type", [AuthType.SAML, AuthType.OIDC])
def test_verify_email_is_invited_skips_whitelist_for_sso(
    monkeypatch: pytest.MonkeyPatch, auth_type: AuthType
) -> None:
    monkeypatch.setattr(users, "AUTH_TYPE", auth_type, raising=False)
    monkeypatch.setattr(users, "workspace_invite_only_enabled", lambda: True)
    monkeypatch.setattr(
        users,
        "get_invited_users",
        lambda: ["allowed@example.com"],
        raising=False,
    )

    # Should not raise even though whitelist is populated
    verify_email_is_invited("newuser@example.com")


def test_verify_email_is_invited_enforced_for_basic_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(users, "AUTH_TYPE", AuthType.BASIC, raising=False)
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
    monkeypatch.setattr(users, "AUTH_TYPE", AuthType.BASIC, raising=False)
    monkeypatch.setattr(users, "workspace_invite_only_enabled", lambda: False)
    monkeypatch.setattr(
        users,
        "get_invited_users",
        lambda: ["allowed@example.com"],
        raising=False,
    )

    verify_email_is_invited("newuser@example.com")
