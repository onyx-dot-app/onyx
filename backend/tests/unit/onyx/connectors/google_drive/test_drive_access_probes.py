"""Access probes must tell "no access" apart from a temporary failure.

Reading a 429, a rate-limit 403, or a 500 as "no access" would reject a drive's
organizer or skip the drive, and a prune would then delete its documents.
"""

from unittest.mock import MagicMock, patch

import httplib2
import pytest
from googleapiclient.errors import HttpError

from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.google_drive.source_operations import (
    GoogleDriveHttpError,
    GoogleDriveSourceOperations,
)

_RATE_LIMIT_BODY = (
    b'{"error": {"errors": [{"reason": "userRateLimitExceeded"}], '
    b'"message": "userRateLimitExceeded"}}'
)


def _error(status: int, body: bytes = b"{}") -> HttpError:
    return HttpError(httplib2.Response({"status": status}), body)


def _service(drives_get: list[object], files_list: list[object]) -> MagicMock:
    """Each request returns or raises the next outcome in its list."""

    def _request(outcomes: list[object]) -> MagicMock:
        request = MagicMock()

        def _execute() -> object:
            outcome = outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        request.execute.side_effect = _execute
        return request

    service = MagicMock()
    service.drives.return_value.get.return_value = _request(drives_get)
    service.files.return_value.list.return_value = _request(files_list)
    return service


def can_list_drive(service: MagicMock, drive_id: str) -> bool:
    ops = GoogleDriveSourceOperations(
        credentials_provider=OnyxStaticCredentialsProvider(None, "google_drive", {})
    )
    with patch.object(GoogleDriveSourceOperations, "_drive", return_value=service):
        return ops.can_list_drive(user_email="user@co.com", drive_id=drive_id)


@pytest.fixture(autouse=True)
def _no_sleep() -> object:
    with patch("onyx.connectors.google_utils.google_utils.time.sleep"):
        yield


def test_member_who_can_list_is_accepted() -> None:
    assert can_list_drive(_service([{"id": "d"}], [{"files": []}]), "d") is True


@pytest.mark.parametrize("status", [403, 404])
def test_denied_drive_get_rejects_candidate(status: int) -> None:
    assert can_list_drive(_service([_error(status)], [{"files": []}]), "d") is False


def test_empty_listing_without_membership_is_not_access() -> None:
    """files.list can succeed with zero items for a non-member; drives.get is
    what shows the drive is out of reach."""
    service = _service([_error(404)], [{"files": []}])

    assert can_list_drive(service, "d") is False
    service.files.return_value.list.return_value.execute.assert_not_called()


def test_rate_limit_403_is_retried_not_read_as_denial() -> None:
    service = _service([_error(403, _RATE_LIMIT_BODY), {"id": "d"}], [{"files": []}])

    assert can_list_drive(service, "d") is True


def test_transient_server_error_is_retried() -> None:
    service = _service([_error(500), {"id": "d"}], [{"files": []}])

    assert can_list_drive(service, "d") is True


def test_persistent_server_error_raises() -> None:
    service = _service([_error(503)] * 3, [{"files": []}])

    with pytest.raises(GoogleDriveHttpError) as error:
        can_list_drive(service, "d")
    assert error.value.status_code == 503
