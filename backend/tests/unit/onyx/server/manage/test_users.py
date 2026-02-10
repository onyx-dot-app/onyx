from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import onyx.server.manage.users as users_api


def _setup_bulk_invite_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _validate_email(
        email: str, check_deliverability: bool = False
    ) -> SimpleNamespace:
        _ = check_deliverability
        return SimpleNamespace(normalized=email.lower())

    def _get_all_users(_db_session: object) -> list[object]:
        return []

    def _noop(*_call_args: object, **_call_kwargs: object) -> None:
        return None

    def _ee_noop(*_args: object, **_kwargs: object):
        return _noop

    monkeypatch.setattr(users_api, "MULTI_TENANT", False, raising=False)
    monkeypatch.setattr(users_api, "DEV_MODE", False, raising=False)
    monkeypatch.setattr(users_api, "ENABLE_EMAIL_INVITES", True, raising=False)
    monkeypatch.setattr(users_api, "get_current_tenant_id", lambda: "tenant-id")
    monkeypatch.setattr(users_api, "validate_email", _validate_email)
    monkeypatch.setattr(users_api, "get_all_users", _get_all_users)
    monkeypatch.setattr(users_api, "get_invited_users", lambda: [])
    monkeypatch.setattr(users_api, "write_invited_users", lambda emails: len(emails))
    monkeypatch.setattr(users_api, "fetch_ee_implementation_or_noop", _ee_noop)


def test_bulk_invite_users_returns_warning_when_email_send_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _setup_bulk_invite_dependencies(monkeypatch)
    monkeypatch.setattr(
        users_api,
        "send_user_email_invite",
        MagicMock(side_effect=RuntimeError("SMTP not available")),
    )

    response = users_api.bulk_invite_users(
        emails=["NewUser@Example.com"],
        current_user=SimpleNamespace(email="admin@example.com"),
        db_session=MagicMock(),
    )

    assert response.number_of_invited_users == 1
    assert response.email_invite_warning is not None
    assert "couldn't confirm" in response.email_invite_warning


def test_bulk_invite_users_has_no_warning_when_email_send_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _setup_bulk_invite_dependencies(monkeypatch)
    send_user_email_invite_mock = MagicMock()
    monkeypatch.setattr(
        users_api,
        "send_user_email_invite",
        send_user_email_invite_mock,
    )

    response = users_api.bulk_invite_users(
        emails=["newuser@example.com"],
        current_user=SimpleNamespace(email="admin@example.com"),
        db_session=MagicMock(),
    )

    send_user_email_invite_mock.assert_called_once()
    assert response.number_of_invited_users == 1
    assert response.email_invite_warning is None


def test_bulk_invite_users_warns_when_email_invites_are_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _setup_bulk_invite_dependencies(monkeypatch)
    monkeypatch.setattr(users_api, "ENABLE_EMAIL_INVITES", False, raising=False)
    send_user_email_invite_mock = MagicMock()
    monkeypatch.setattr(
        users_api,
        "send_user_email_invite",
        send_user_email_invite_mock,
    )

    response = users_api.bulk_invite_users(
        emails=["newuser@example.com"],
        current_user=SimpleNamespace(email="admin@example.com"),
        db_session=MagicMock(),
    )

    send_user_email_invite_mock.assert_not_called()
    assert response.number_of_invited_users == 1
    assert response.email_invite_warning is not None
    assert "email invitations are disabled" in response.email_invite_warning
