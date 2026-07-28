"""Guards the reclaim_license_task gating contract: it re-claims only for
self-hosted deployments whose license is expired or near expiry, swallows
control-plane failures, and stays registered on the 6-hour beat schedule."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
import requests

from ee.onyx.background.celery.tasks.beat_schedule import ee_tasks_to_schedule
from ee.onyx.background.celery.tasks.license_reclaim.tasks import reclaim_license_task
from ee.onyx.server.license.models import LicenseSource
from ee.onyx.utils.license import StoredLicense
from onyx.configs.constants import OnyxCeleryTask

TASKS_MODULE = "ee.onyx.background.celery.tasks.license_reclaim.tasks"


def _make_payload(
    *,
    expires_delta: timedelta,
    source: LicenseSource = LicenseSource.AUTO_FETCH,
) -> MagicMock:
    payload = MagicMock()
    payload.tenant_id = "tenant_123"
    payload.expires_at = datetime.now(timezone.utc) + expires_delta
    # Explicit: a bare MagicMock attribute is neither enum member, which reads
    # as re-fetchable and silently skips the manual-license guard.
    payload.source = source
    return payload


class TestManualLicensesAreNotReclaimed:
    def test_manual_license_never_calls_the_control_plane(self) -> None:
        """A license with no Stripe customer is issued and replaced by sales,
        so the control plane has nothing newer to return."""
        with (
            patch(f"{TASKS_MODULE}.get_session_with_current_tenant") as mock_session,
            patch(f"{TASKS_MODULE}.load_verified_license") as mock_load,
            patch(f"{TASKS_MODULE}.reclaim_license_from_control_plane") as mock_reclaim,
        ):
            mock_session.return_value.__enter__.return_value = MagicMock()
            mock_load.return_value = StoredLicense(
                "stored-blob",
                _make_payload(
                    expires_delta=timedelta(days=1),
                    source=LicenseSource.MANUAL_UPLOAD,
                ),
            )
            reclaim_license_task(tenant_id="tenant_123")

        mock_reclaim.assert_not_called()


class TestReclaimLicenseTask:
    @pytest.mark.parametrize(
        ("expires_delta", "should_reclaim"),
        [
            (timedelta(days=20), False),
            (timedelta(days=3), True),
            (timedelta(days=-1), True),
        ],
    )
    def test_reclaims_only_when_license_is_expired_or_near_expiry(
        self,
        expires_delta: timedelta,
        should_reclaim: bool,
    ) -> None:
        db_session = MagicMock()
        with (
            patch(f"{TASKS_MODULE}.get_session_with_current_tenant") as mock_session,
            patch(f"{TASKS_MODULE}.load_verified_license") as mock_load,
            patch(f"{TASKS_MODULE}.reclaim_license_from_control_plane") as mock_reclaim,
        ):
            mock_session.return_value.__enter__.return_value = db_session
            mock_load.return_value = StoredLicense(
                "stored-blob", _make_payload(expires_delta=expires_delta)
            )

            reclaim_license_task(tenant_id="tenant_123")

        if should_reclaim:
            mock_reclaim.assert_called_once_with(db_session)
        else:
            mock_reclaim.assert_not_called()

    def test_noops_when_no_license_is_stored(self) -> None:
        with (
            patch(f"{TASKS_MODULE}.get_session_with_current_tenant") as mock_session,
            patch(f"{TASKS_MODULE}.load_verified_license") as mock_load,
            patch(f"{TASKS_MODULE}.reclaim_license_from_control_plane") as mock_reclaim,
        ):
            mock_session.return_value.__enter__.return_value = MagicMock()
            mock_load.return_value = None

            reclaim_license_task(tenant_id="tenant_123")

        mock_reclaim.assert_not_called()

    def test_noops_for_multi_tenant(self) -> None:
        with (
            patch(f"{TASKS_MODULE}.MULTI_TENANT", True),
            patch(f"{TASKS_MODULE}.get_session_with_current_tenant") as mock_session,
            patch(f"{TASKS_MODULE}.reclaim_license_from_control_plane") as mock_reclaim,
        ):
            reclaim_license_task(tenant_id="tenant_123")

        mock_session.assert_not_called()
        mock_reclaim.assert_not_called()

    @pytest.mark.parametrize(
        "reclaim_error",
        [requests.ConnectionError("control plane down"), ValueError("bad license")],
    )
    def test_swallows_reclaim_failures(self, reclaim_error: Exception) -> None:
        with (
            patch(f"{TASKS_MODULE}.get_session_with_current_tenant") as mock_session,
            patch(f"{TASKS_MODULE}.load_verified_license") as mock_load,
            patch(f"{TASKS_MODULE}.reclaim_license_from_control_plane") as mock_reclaim,
            patch(f"{TASKS_MODULE}.logger") as mock_logger,
        ):
            mock_session.return_value.__enter__.return_value = MagicMock()
            mock_load.return_value = StoredLicense(
                "stored-blob", _make_payload(expires_delta=timedelta(days=1))
            )
            mock_reclaim.side_effect = reclaim_error

            reclaim_license_task(tenant_id="tenant_123")

        mock_logger.warning.assert_called_once()


def test_reclaim_license_task_is_scheduled_every_six_hours() -> None:
    reclaim_schedule = next(
        task
        for task in ee_tasks_to_schedule
        if task["task"] == OnyxCeleryTask.RECLAIM_LICENSE
    )

    assert reclaim_schedule["name"] == "reclaim-license"
    assert reclaim_schedule["schedule"] == timedelta(hours=6)
    assert reclaim_schedule["options"]["expires"] is not None


class TestTerminalAuthRejection:
    """The block lives in reclaim_license_from_control_plane so every entry
    point honors it. The task only distinguishes the log level."""

    def _run_with_error(self, error: Exception) -> MagicMock:
        with (
            patch(f"{TASKS_MODULE}.get_session_with_current_tenant") as mock_session,
            patch(f"{TASKS_MODULE}.load_verified_license") as mock_load,
            patch(f"{TASKS_MODULE}.reclaim_license_from_control_plane") as mock_reclaim,
            patch(f"{TASKS_MODULE}.logger") as mock_logger,
        ):
            mock_session.return_value.__enter__.return_value = MagicMock()
            mock_load.return_value = StoredLicense(
                "stored-blob", _make_payload(expires_delta=timedelta(days=1))
            )
            mock_reclaim.side_effect = error
            reclaim_license_task(tenant_id="tenant_123")
        return mock_logger

    def _http_error(self, status_code: int) -> requests.HTTPError:
        response = MagicMock()
        response.status_code = status_code
        return requests.HTTPError(response=response)

    @pytest.mark.parametrize("status_code", [401, 403])
    def test_auth_rejection_is_logged_as_terminal(self, status_code: int) -> None:
        mock_logger = self._run_with_error(self._http_error(status_code))

        mock_logger.error.assert_called_once()
        mock_logger.warning.assert_not_called()

    @pytest.mark.parametrize("status_code", [500, 502, 429])
    def test_transient_http_failure_keeps_retrying(self, status_code: int) -> None:
        mock_logger = self._run_with_error(self._http_error(status_code))

        mock_logger.warning.assert_called_once()
        mock_logger.error.assert_not_called()

    def test_connection_error_keeps_retrying(self) -> None:
        mock_logger = self._run_with_error(
            requests.ConnectionError("control plane down")
        )

        mock_logger.warning.assert_called_once()
        mock_logger.error.assert_not_called()
