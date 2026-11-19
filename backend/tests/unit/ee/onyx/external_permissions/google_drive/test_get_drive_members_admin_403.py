import time
from unittest.mock import MagicMock

import pytest

from ee.onyx.external_permissions.google_drive.group_sync import _get_drive_members
from onyx.connectors.google_drive.source_operations import (
    GoogleDriveHttpError,
    GoogleDriveSourceOperations,
)


def _make_http_error(status: int) -> GoogleDriveHttpError:
    return GoogleDriveHttpError(
        status_code=status,
        reasons=(),
        access_denied=status in (403, 404),
        message="Forbidden" if status == 403 else "Server Error",
    )


def _make_connector(admin_error: GoogleDriveHttpError) -> MagicMock:
    connector = MagicMock()
    connector.primary_admin_email = "admin@example.com"
    connector.get_all_drive_ids.return_value = ["drive-1"]
    ops = MagicMock(spec=GoogleDriveSourceOperations)
    ops.get_admin_user.side_effect = admin_error
    connector.ops = ops
    return connector


def test_get_drive_members_admin_403_raises_permission_error() -> None:
    """A 403 on the primary-admin lookup must become a PermissionError so
    the caller in external_group_syncing can mark the attempt as a clean
    credential failure instead of an unhandled Celery exception."""
    connector = _make_connector(_make_http_error(403))

    with pytest.raises(PermissionError) as exc_info:
        _get_drive_members(connector, deadline=time.monotonic() + 60)

    assert "primary admin" in str(exc_info.value).lower()
    assert connector.primary_admin_email in str(exc_info.value)
    connector.ops.list_drive_members.assert_not_called()


def test_get_drive_members_admin_non_403_reraised() -> None:
    """A non-403 HTTP error on the admin lookup (e.g. 500) should still
    propagate as the original exception — only 403 gets the clean
    credential-invalid conversion."""
    connector = _make_connector(_make_http_error(500))

    with pytest.raises(GoogleDriveHttpError) as exc_info:
        _get_drive_members(connector, deadline=time.monotonic() + 60)

    assert exc_info.value.status_code == 500


def _rate_limit_error() -> GoogleDriveHttpError:
    """Google's 403 for a rate limit: not an access denial."""
    return GoogleDriveHttpError(
        status_code=403,
        reasons=("rateLimitExceeded",),
        access_denied=False,
        message="Rate Limit Exceeded",
    )


def test_a_rate_limited_admin_lookup_is_not_a_permission_error() -> None:
    connector = _make_connector(_rate_limit_error())

    with pytest.raises(GoogleDriveHttpError) as exc_info:
        _get_drive_members(connector, deadline=time.monotonic() + 60)

    assert exc_info.value.rate_limited


def _connector_with_drive_member_error(error: GoogleDriveHttpError) -> MagicMock:
    connector = MagicMock()
    connector.primary_admin_email = "admin@example.com"
    connector.get_all_drive_ids.return_value = ["drive-1"]
    ops = MagicMock(spec=GoogleDriveSourceOperations)
    ops.get_admin_user.return_value = MagicMock(is_admin=True, is_delegated_admin=False)
    ops.list_drive_members.side_effect = error
    connector.ops = ops
    return connector


def test_a_rate_limited_drive_member_read_fails_the_sync() -> None:
    """A drive with no members would remove its users' access, so a rate
    refusal must not read as "no access"."""
    connector = _connector_with_drive_member_error(_rate_limit_error())

    with pytest.raises(GoogleDriveHttpError):
        _get_drive_members(connector, deadline=time.monotonic() + 60)


def test_a_denied_drive_member_read_leaves_the_drive_with_no_members() -> None:
    connector = _connector_with_drive_member_error(_make_http_error(403))

    members = _get_drive_members(connector, deadline=time.monotonic() + 60)

    assert members == {"drive-1": (set(), set())}
