"""Test bulk invite limit for free trial tenants."""

from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.manage.models import EmailInviteStatus
from onyx.server.manage.models import UserByEmail
from onyx.server.manage.users import bulk_invite_users
from onyx.server.manage.users import remove_invited_user


def _make_shared_session_mock(next_total: int) -> MagicMock:
    """Build a MagicMock mirroring `get_session_with_shared_schema`.

    The production code does one `INSERT ... ON CONFLICT DO UPDATE ...
    RETURNING total_invites_sent` call against the shared-schema session.
    The mock plays the role of that session: calling the patched factory
    returns a context manager whose `__enter__` yields a session whose
    `.execute(...).scalar_one()` answers with `next_total` — the
    post-increment counter value the DB would have returned.
    """
    session = MagicMock()
    session.execute.return_value.scalar_one.return_value = next_total

    @contextmanager
    def _ctx() -> Iterator[MagicMock]:
        yield session

    mock = MagicMock(side_effect=_ctx)
    return mock


@patch(
    "onyx.server.manage.users.get_session_with_shared_schema",
    new_callable=lambda: _make_shared_session_mock(next_total=6),
)
@patch("onyx.server.manage.users.enforce_invite_rate_limit")
@patch("onyx.server.manage.users.MULTI_TENANT", True)
@patch("onyx.server.manage.users.is_tenant_on_trial_fn", return_value=True)
@patch("onyx.server.manage.users.get_current_tenant_id", return_value="test_tenant")
@patch("onyx.server.manage.users.get_invited_users", return_value=[])
@patch("onyx.server.manage.users.get_all_users", return_value=[])
@patch("onyx.server.manage.users.enforce_seat_limit")
@patch("onyx.server.manage.users.NUM_FREE_TRIAL_USER_INVITES", 5)
def test_trial_tenant_cannot_exceed_invite_limit(*_mocks: None) -> None:
    """Post-upsert total of 6 exceeds cap=5 — must raise OnyxError."""
    emails = [f"user{i}@example.com" for i in range(6)]

    with pytest.raises(OnyxError) as exc_info:
        bulk_invite_users(emails=emails, current_user=MagicMock())

    assert exc_info.value.error_code == OnyxErrorCode.TRIAL_INVITE_LIMIT_EXCEEDED
    assert "invite limit" in exc_info.value.detail.lower()


@patch(
    "onyx.server.manage.users.get_session_with_shared_schema",
    new_callable=lambda: _make_shared_session_mock(next_total=3),
)
@patch("onyx.server.manage.users.enforce_invite_rate_limit")
@patch("onyx.server.manage.users.get_redis_client")
@patch("onyx.server.manage.users.MULTI_TENANT", True)
@patch("onyx.server.manage.users.DEV_MODE", True)
@patch("onyx.server.manage.users.ENABLE_EMAIL_INVITES", False)
@patch("onyx.server.manage.users.is_tenant_on_trial_fn", return_value=True)
@patch("onyx.server.manage.users.get_current_tenant_id", return_value="test_tenant")
@patch("onyx.server.manage.users.get_invited_users", return_value=[])
@patch("onyx.server.manage.users.get_all_users", return_value=[])
@patch("onyx.server.manage.users.write_invited_users", return_value=3)
@patch("onyx.server.manage.users.enforce_seat_limit")
@patch("onyx.server.manage.users.NUM_FREE_TRIAL_USER_INVITES", 5)
@patch(
    "onyx.server.manage.users.fetch_ee_implementation_or_noop",
    return_value=lambda *_args: None,
)
def test_trial_tenant_can_invite_within_limit(*_mocks: None) -> None:
    """Post-upsert total of 3 fits under cap=5 — must succeed."""
    emails = ["user1@example.com", "user2@example.com", "user3@example.com"]

    result = bulk_invite_users(emails=emails, current_user=MagicMock())

    assert result.invited_count == 3
    assert result.email_invite_status == EmailInviteStatus.DISABLED


@patch("onyx.server.manage.users.get_session_with_shared_schema")
@patch("onyx.server.manage.users.enforce_invite_rate_limit")
@patch("onyx.server.manage.users.MULTI_TENANT", True)
@patch("onyx.server.manage.users.DEV_MODE", True)
@patch("onyx.server.manage.users.ENABLE_EMAIL_INVITES", False)
@patch("onyx.server.manage.users.is_tenant_on_trial_fn", return_value=False)
@patch("onyx.server.manage.users.get_current_tenant_id", return_value="test_tenant")
@patch("onyx.server.manage.users.get_invited_users", return_value=[])
@patch("onyx.server.manage.users.get_all_users", return_value=[])
@patch("onyx.server.manage.users.write_invited_users", return_value=3)
@patch("onyx.server.manage.users.enforce_seat_limit")
@patch(
    "onyx.server.manage.users.fetch_ee_implementation_or_noop",
    return_value=lambda *_args: None,
)
def test_paid_tenant_bypasses_invite_counter(
    _ee_fetch: MagicMock,
    _seat_limit: MagicMock,
    _write_invited: MagicMock,
    _get_all_users: MagicMock,
    _get_invited_users: MagicMock,
    _get_tenant_id: MagicMock,
    _is_trial: MagicMock,
    _rate_limit: MagicMock,
    mock_get_session: MagicMock,
) -> None:
    """Paid tenants must not read or write the invite counter at all."""
    emails = [f"user{i}@example.com" for i in range(3)]

    result = bulk_invite_users(emails=emails, current_user=MagicMock())

    mock_get_session.assert_not_called()
    assert result.invited_count == 3


# --- email_invite_status tests ---

_COMMON_PATCHES = [
    patch("onyx.server.manage.users.MULTI_TENANT", False),
    patch("onyx.server.manage.users.get_current_tenant_id", return_value="test_tenant"),
    patch("onyx.server.manage.users.get_invited_users", return_value=[]),
    patch("onyx.server.manage.users.get_all_users", return_value=[]),
    patch("onyx.server.manage.users.write_invited_users", return_value=1),
    patch("onyx.server.manage.users.enforce_seat_limit"),
    patch("onyx.server.manage.users.enforce_invite_rate_limit"),
]


def _with_common_patches(fn: object) -> object:
    for p in reversed(_COMMON_PATCHES):
        fn = p(fn)  # ty: ignore[no-matching-overload]
    return fn


@_with_common_patches
@patch("onyx.server.manage.users.ENABLE_EMAIL_INVITES", False)
def test_email_invite_status_disabled(*_mocks: None) -> None:
    """When email invites are disabled, status is disabled."""
    result = bulk_invite_users(emails=["user@example.com"], current_user=MagicMock())

    assert result.email_invite_status == EmailInviteStatus.DISABLED


@_with_common_patches
@patch("onyx.server.manage.users.ENABLE_EMAIL_INVITES", True)
@patch("onyx.server.manage.users.EMAIL_CONFIGURED", False)
def test_email_invite_status_not_configured(*_mocks: None) -> None:
    """When email invites are enabled but no server is configured, status is not_configured."""
    result = bulk_invite_users(emails=["user@example.com"], current_user=MagicMock())

    assert result.email_invite_status == EmailInviteStatus.NOT_CONFIGURED


@_with_common_patches
@patch("onyx.server.manage.users.ENABLE_EMAIL_INVITES", True)
@patch("onyx.server.manage.users.EMAIL_CONFIGURED", True)
@patch("onyx.server.manage.users.send_user_email_invite")
def test_email_invite_status_sent(mock_send: MagicMock, *_mocks: None) -> None:
    """When email invites are enabled and configured, status is sent."""
    result = bulk_invite_users(emails=["user@example.com"], current_user=MagicMock())

    mock_send.assert_called_once()
    assert result.email_invite_status == EmailInviteStatus.SENT


@_with_common_patches
@patch("onyx.server.manage.users.ENABLE_EMAIL_INVITES", True)
@patch("onyx.server.manage.users.EMAIL_CONFIGURED", True)
@patch(
    "onyx.server.manage.users.send_user_email_invite",
    side_effect=Exception("SMTP auth failed"),
)
def test_email_invite_status_send_failed(*_mocks: None) -> None:
    """When email sending throws, status is send_failed and invite is still saved."""
    result = bulk_invite_users(emails=["user@example.com"], current_user=MagicMock())

    assert result.email_invite_status == EmailInviteStatus.SEND_FAILED
    assert result.invited_count == 1


# --- trial-only rate limit gating tests (remove-invited-user) ---


@patch("onyx.server.manage.users.enforce_remove_invited_rate_limit")
@patch("onyx.server.manage.users.remove_user_from_invited_users", return_value=0)
@patch("onyx.server.manage.users.MULTI_TENANT", True)
@patch("onyx.server.manage.users.DEV_MODE", True)
@patch("onyx.server.manage.users.is_tenant_on_trial_fn", return_value=False)
@patch("onyx.server.manage.users.get_current_tenant_id", return_value="test_tenant")
@patch(
    "onyx.server.manage.users.fetch_ee_implementation_or_noop",
    return_value=lambda *_args: None,
)
def test_paid_tenant_bypasses_remove_invited_rate_limit(
    _ee_fetch: MagicMock,
    _get_tenant_id: MagicMock,
    _is_trial: MagicMock,
    _remove_from_invited: MagicMock,
    mock_rate_limit: MagicMock,
) -> None:
    """Paid tenants must not hit the remove-invited rate limiter at all."""
    remove_invited_user(
        user_email=UserByEmail(user_email="user@example.com"),
        current_user=MagicMock(),
        db_session=MagicMock(),
    )
    mock_rate_limit.assert_not_called()


@patch("onyx.server.manage.users.enforce_remove_invited_rate_limit")
@patch("onyx.server.manage.users.remove_user_from_invited_users", return_value=0)
@patch("onyx.server.manage.users.get_redis_client")
@patch("onyx.server.manage.users.MULTI_TENANT", True)
@patch("onyx.server.manage.users.DEV_MODE", True)
@patch("onyx.server.manage.users.is_tenant_on_trial_fn", return_value=True)
@patch("onyx.server.manage.users.get_current_tenant_id", return_value="test_tenant")
@patch(
    "onyx.server.manage.users.fetch_ee_implementation_or_noop",
    return_value=lambda *_args: None,
)
def test_trial_tenant_hits_remove_invited_rate_limit(
    _ee_fetch: MagicMock,
    _get_tenant_id: MagicMock,
    _is_trial: MagicMock,
    _get_redis: MagicMock,
    _remove_from_invited: MagicMock,
    mock_rate_limit: MagicMock,
) -> None:
    """Trial tenants must flow through the remove-invited rate limiter."""
    remove_invited_user(
        user_email=UserByEmail(user_email="user@example.com"),
        current_user=MagicMock(),
        db_session=MagicMock(),
    )
    mock_rate_limit.assert_called_once()
