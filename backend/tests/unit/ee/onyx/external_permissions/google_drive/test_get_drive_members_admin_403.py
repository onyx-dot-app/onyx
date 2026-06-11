from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from googleapiclient.errors import HttpError

from ee.onyx.external_permissions.google_drive.group_sync import _get_drive_members


def _make_http_error(status: int) -> HttpError:
    resp = MagicMock()
    resp.status = status
    resp.reason = "Forbidden" if status == 403 else "Not Found"
    return HttpError(resp=resp, content=b"{}")


def _make_connector() -> MagicMock:
    connector = MagicMock()
    connector.creds = MagicMock()
    connector.primary_admin_email = "admin@example.com"
    connector.get_all_drive_ids.return_value = ["drive-1"]
    return connector


@patch("ee.onyx.external_permissions.google_drive.group_sync.get_drive_service")
def test_get_drive_members_admin_403_raises_permission_error(
    mock_get_drive_service: MagicMock,
) -> None:
    """A 403 on the primary-admin lookup must become a PermissionError so
    the caller in external_group_syncing can mark the attempt as a clean
    credential failure instead of an unhandled Celery exception."""
    mock_get_drive_service.return_value = MagicMock()
    connector = _make_connector()
    admin_service = MagicMock()
    admin_service.users.return_value.get.return_value.execute.side_effect = (
        _make_http_error(403)
    )

    with pytest.raises(PermissionError) as exc_info:
        _get_drive_members(connector, admin_service)

    assert "primary admin" in str(exc_info.value).lower()
    assert connector.primary_admin_email in str(exc_info.value)


@patch("ee.onyx.external_permissions.google_drive.group_sync.get_drive_service")
def test_get_drive_members_admin_non_403_reraised(
    mock_get_drive_service: MagicMock,
) -> None:
    """A non-403 HttpError on the admin lookup (e.g. 500) should still
    propagate as the original exception — only 403 gets the clean
    credential-invalid conversion."""
    mock_get_drive_service.return_value = MagicMock()
    connector = _make_connector()
    admin_service = MagicMock()
    admin_service.users.return_value.get.return_value.execute.side_effect = (
        _make_http_error(500)
    )

    with pytest.raises(HttpError):
        _get_drive_members(connector, admin_service)
