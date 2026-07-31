"""Guards the reclaim_license_task gating contract: it re-claims only for
self-hosted deployments whose license is expired or near expiry, swallows
control-plane failures, and throttles its own control-plane attempts so its
triggers (request-path debounce, periodic poller) can fire it freely."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
import requests

from ee.onyx.background.celery.tasks.beat_schedule import ee_tasks_to_schedule
from ee.onyx.background.celery.tasks.license_reclaim.tasks import reclaim_license_task
from ee.onyx.server.license.models import LicenseSource
from ee.onyx.utils.license import LicenseRejectedError, StoredLicense
from onyx.configs.constants import OnyxCeleryTask

TASKS_MODULE = "ee.onyx.background.celery.tasks.license_reclaim.tasks"


def _make_payload(
    *,
    expires_delta: timedelta,
    source: LicenseSource = LicenseSource.AUTO_FETCH,
    issued_delta: timedelta = timedelta(days=-30),
) -> MagicMock:
    payload = MagicMock()
    payload.tenant_id = "tenant_123"
    payload.expires_at = datetime.now(timezone.utc) + expires_delta
    # Real datetime: the backoff compares issue dates to tell a renewal from a
    # control plane with nothing new, and MagicMock has no ordering.
    payload.issued_at = datetime.now(timezone.utc) + issued_delta
    # Explicit: a bare MagicMock attribute equals neither enum member, so it
    # reads as re-fetchable and silently skips the manual-license guard.
    payload.source = source
    return payload


def _renewal_of(payload: MagicMock) -> MagicMock:
    """What the control plane returns when a renewal really did happen."""
    renewed = MagicMock()
    renewed.issued_at = payload.issued_at + timedelta(days=1)
    renewed.expires_at = payload.expires_at + timedelta(days=30)
    return renewed


def _unchanged_from(payload: MagicMock) -> MagicMock:
    """What it returns for a customer who lapsed instead of renewing: the same
    license back, issue date and all."""
    unchanged = MagicMock()
    unchanged.issued_at = payload.issued_at
    unchanged.expires_at = payload.expires_at
    return unchanged


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
            payload = _make_payload(expires_delta=expires_delta)
            mock_session.return_value.__enter__.return_value = db_session
            mock_load.return_value = StoredLicense("stored-blob", payload)
            mock_reclaim.return_value = _renewal_of(payload)

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


def test_reclaim_runs_only_when_something_asks_for_it() -> None:
    """No beat entry: an idle instance is covered by the daily expiry task, and
    an instance with traffic by the request-path scheduler. A beat on top would
    be a third caller polling for a renewal the other two already fetch."""
    assert not [
        task
        for task in ee_tasks_to_schedule
        if task["task"] == OnyxCeleryTask.RECLAIM_LICENSE
    ]


class TestTerminalAuthRejection:
    """The block lives in reclaim_license_from_control_plane so every entry
    point honors it. The task branches on the type it raises, not on a status
    code it re-derives from the exception."""

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

    def test_rejection_is_logged_as_terminal(self) -> None:
        mock_logger = self._run_with_error(
            LicenseRejectedError("Invalid license: Invalid license signature")
        )

        mock_logger.error.assert_called_once()
        mock_logger.warning.assert_not_called()

    def test_the_upstream_reason_reaches_the_log(self) -> None:
        """An admin reading the log needs to know which refusal it was."""
        mock_logger = self._run_with_error(LicenseRejectedError("Invalid license: bad"))

        assert "Invalid license: bad" in str(mock_logger.error.call_args)

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


class TestReclaimCadence:
    """The task can be triggered far more often than a reclaim should reach
    the control plane, so this gate keeps trigger cadence from becoming
    control-plane polling cadence."""

    def _run(
        self,
        expires_delta: timedelta,
        *,
        slot_free: bool = True,
        idle_rounds: int = 0,
        renewal: bool = True,
        reclaim_error: Exception | None = None,
        redis_down: bool = False,
    ) -> tuple[MagicMock, MagicMock]:
        with (
            patch(f"{TASKS_MODULE}.get_session_with_current_tenant") as mock_session,
            patch(f"{TASKS_MODULE}.load_verified_license") as mock_load,
            patch(f"{TASKS_MODULE}.reclaim_license_from_control_plane") as mock_reclaim,
            patch(f"{TASKS_MODULE}.get_redis_client") as mock_redis,
        ):
            payload = _make_payload(expires_delta=expires_delta)
            mock_session.return_value.__enter__.return_value = MagicMock()
            mock_load.return_value = StoredLicense("stored-blob", payload)
            if reclaim_error is not None:
                mock_reclaim.side_effect = reclaim_error
            else:
                mock_reclaim.return_value = (
                    _renewal_of(payload) if renewal else _unchanged_from(payload)
                )
            if redis_down:
                mock_redis.side_effect = ConnectionError("redis down")
            else:
                mock_redis.return_value.set.return_value = slot_free
                mock_redis.return_value.get.return_value = str(idle_rounds).encode()
            reclaim_license_task(tenant_id="tenant_123")
        return mock_reclaim, mock_redis

    def test_a_run_outside_the_window_touches_nothing(self) -> None:
        """This is the common case on every instance, so it has to stay a local
        expiry check rather than a control-plane request."""
        mock_reclaim, mock_redis = self._run(timedelta(days=20))

        mock_reclaim.assert_not_called()
        mock_redis.assert_not_called()

    def test_a_taken_slot_blocks_the_control_plane_call(self) -> None:
        mock_reclaim, _ = self._run(timedelta(days=3), slot_free=False)

        mock_reclaim.assert_not_called()

    def test_a_free_slot_reaches_the_control_plane(self) -> None:
        mock_reclaim, _ = self._run(timedelta(days=3))

        mock_reclaim.assert_called_once()

    @pytest.mark.parametrize(
        ("expires_delta", "expected_interval"),
        [
            (timedelta(days=3), 6 * 60 * 60),
            (timedelta(minutes=30), 60),
            (timedelta(days=-1), 60),
        ],
        ids=["lead-up", "period-ending", "already-expired"],
    )
    def test_the_interval_tightens_as_the_period_ends(
        self, expires_delta: timedelta, expected_interval: int
    ) -> None:
        _, mock_redis = self._run(expires_delta)

        assert mock_redis.return_value.set.call_args.kwargs["ex"] == expected_interval

    @pytest.mark.parametrize(
        ("idle_rounds", "expected_interval"),
        [(0, 60), (1, 120), (3, 480), (4, 900), (99, 900)],
    )
    def test_repeated_futile_attempts_widen_the_interval(
        self, idle_rounds: int, expected_interval: int
    ) -> None:
        """A customer who lapsed rather than renewed would otherwise be polled
        at the renewal rate for the whole grace period, against a control plane
        that has nothing to return."""
        _, mock_redis = self._run(timedelta(days=-1), idle_rounds=idle_rounds)

        assert mock_redis.return_value.set.call_args.kwargs["ex"] == expected_interval

    def test_a_renewal_resets_the_backoff(self) -> None:
        _, mock_redis = self._run(timedelta(days=-1), idle_rounds=5)

        mock_redis.return_value.delete.assert_called_once()
        mock_redis.return_value.pipeline.return_value.incr.assert_not_called()

    def test_nothing_newer_widens_the_backoff(self) -> None:
        _, mock_redis = self._run(timedelta(days=-1), renewal=False)

        pipe = mock_redis.return_value.pipeline.return_value
        pipe.incr.assert_called_once()
        pipe.execute.assert_called_once()
        mock_redis.return_value.delete.assert_not_called()

    def test_an_unreachable_control_plane_also_backs_off(self) -> None:
        """Retrying a down control plane at the renewal rate helps nobody."""
        _, mock_redis = self._run(
            timedelta(days=-1), reclaim_error=requests.ConnectionError("down")
        )

        mock_redis.return_value.pipeline.return_value.incr.assert_called_once()

    def test_a_redis_outage_still_lets_a_renewal_through(self) -> None:
        """Failing closed would strand a renewed customer on an expired license
        for as long as Redis is down."""
        mock_reclaim, _ = self._run(timedelta(days=-1), redis_down=True)

        mock_reclaim.assert_called_once()


class TestThrottleKeysAreTierScoped:
    """The tier boundary is handled by construction. A lead-up slot lives under
    its own key, so entering the urgent window never has to detect or shorten
    it, and two workers crossing the boundary cannot race on one key."""

    def _claim(self, expires_delta: timedelta) -> tuple[bool, MagicMock]:
        from ee.onyx.background.celery.tasks.license_reclaim.tasks import (
            _reclaim_slot_is_free,
        )

        with patch(f"{TASKS_MODULE}.get_redis_client") as mock_redis:
            mock_redis.return_value.get.return_value = b"0"
            mock_redis.return_value.set.return_value = True
            free = _reclaim_slot_is_free(datetime.now(timezone.utc) + expires_delta)
            return free, mock_redis.return_value.set

    def test_the_two_tiers_use_different_keys(self) -> None:
        """Each tier claims its own key, so the two never share a slot."""
        _, lead_up_set = self._claim(timedelta(days=3))
        _, urgent_set = self._claim(timedelta(minutes=30))

        assert lead_up_set.call_args.args[0] != urgent_set.call_args.args[0]

    @pytest.mark.parametrize(
        ("expires_delta", "expected_interval"),
        [
            (timedelta(days=3), 6 * 60 * 60),
            (timedelta(minutes=30), 60),
            (timedelta(days=-1), 60),
        ],
        ids=["lead-up", "period-ending", "already-expired"],
    )
    def test_each_tier_claims_its_own_interval(
        self, expires_delta: timedelta, expected_interval: int
    ) -> None:
        _, set_call = self._claim(expires_delta)

        assert set_call.call_args.kwargs["ex"] == expected_interval
        assert set_call.call_args.kwargs["nx"] is True
