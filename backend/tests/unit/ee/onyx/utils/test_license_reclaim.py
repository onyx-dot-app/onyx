"""Guards the license persistence contract: a blob is stored only after its
signature verifies, and the control-plane re-claim authenticates with the
stored license, validates the response, and persists through the same path.
Also guards the point-of-use scheduler: one debounced reclaim per window,
never an exception into the request that tripped it."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, call, patch

import pytest

from ee.onyx.server.license.models import LicensePayload, LicenseSource, PlanType
from ee.onyx.utils.license import (
    block_license_reclaim,
    license_fingerprint,
    license_reclaim_is_blocked,
    maybe_schedule_license_reclaim,
    publish_license_cache,
    reclaim_license_from_control_plane,
    verify_and_store_license,
)
from ee.onyx.utils.license_expiry import LICENSE_RECLAIM_WINDOW
from onyx.configs.constants import OnyxCeleryPriority, OnyxCeleryTask


def _make_license_payload(stripe_customer_id: str | None = None) -> LicensePayload:
    now = datetime.now(timezone.utc)
    return LicensePayload(
        version="1.0",
        tenant_id="tenant_123",
        organization_name="Test Org",
        issued_at=now - timedelta(days=1),
        expires_at=now + timedelta(days=30),
        seats=10,
        plan_type=PlanType.MONTHLY,
        stripe_customer_id=stripe_customer_id,
    )


class TestLicenseSourceDerivation:
    """Source is a function of the payload, so every writer computes the same
    value and a cache rebuild cannot disagree with the write that preceded it."""

    @pytest.mark.parametrize(
        ("stripe_customer_id", "expected"),
        [
            ("cus_123", LicenseSource.AUTO_FETCH),
            (None, LicenseSource.MANUAL_UPLOAD),
        ],
    )
    def test_source_follows_the_stripe_customer(
        self, stripe_customer_id: str | None, expected: LicenseSource
    ) -> None:
        assert _make_license_payload(stripe_customer_id).source == expected

    def test_manual_upload_of_a_stripe_license_stays_auto_fetch(self) -> None:
        """A hand-uploaded Stripe license is still re-fetchable, so it must not
        read as manual and strand the customer on the sales-managed card."""
        payload = _make_license_payload("cus_123")
        assert payload.source == LicenseSource.AUTO_FETCH


class TestVerifyAndStoreLicense:
    @patch("ee.onyx.utils.license.publish_license_cache")
    @patch("ee.onyx.db.license.upsert_license")
    @patch("ee.onyx.utils.license.verify_license_signature")
    def test_persists_and_caches_the_verified_payload(
        self,
        mock_verify: MagicMock,
        mock_upsert: MagicMock,
        mock_publish_cache: MagicMock,
    ) -> None:
        db_session = MagicMock()
        payload = _make_license_payload()
        mock_verify.return_value = payload

        result = verify_and_store_license(db_session, "signed-license")

        assert result == payload
        mock_upsert.assert_called_once_with(db_session, "signed-license", commit=False)
        mock_publish_cache.assert_called_once_with(payload)

    @patch("ee.onyx.db.license.upsert_license")
    @patch("ee.onyx.utils.license.verify_license_signature")
    def test_rejects_unverifiable_blob_without_persisting(
        self,
        mock_verify: MagicMock,
        mock_upsert: MagicMock,
    ) -> None:
        mock_verify.side_effect = ValueError("Invalid license signature")

        with pytest.raises(ValueError, match="Invalid license signature"):
            verify_and_store_license(MagicMock(), "tampered-license")

        mock_upsert.assert_not_called()


class TestReclaimLicenseFromControlPlane:
    @patch("ee.onyx.utils.license.CLOUD_DATA_PLANE_URL", "https://cloud.example.com")
    @patch("ee.onyx.db.license.get_license")
    @patch("ee.onyx.utils.license.publish_license_cache")
    @patch("ee.onyx.db.license.upsert_license")
    @patch("ee.onyx.utils.license.verify_license_signature")
    @patch("ee.onyx.utils.license.requests.get")
    def test_successfully_reclaims_and_persists_license(
        self,
        mock_get_request: MagicMock,
        mock_verify: MagicMock,
        mock_upsert: MagicMock,
        mock_publish_cache: MagicMock,
        mock_get_license: MagicMock,
    ) -> None:
        db_session = MagicMock()
        payload = _make_license_payload()
        mock_get_license.return_value = MagicMock(license_data="stored-license")
        mock_verify.return_value = payload

        response = MagicMock()
        response.json.return_value = {"license": "signed-license"}
        response.raise_for_status = MagicMock()
        mock_get_request.return_value = response

        result = reclaim_license_from_control_plane(db_session)

        assert result == payload
        mock_get_request.assert_called_once_with(
            "https://cloud.example.com/proxy/license/tenant_123",
            headers={
                "Authorization": "Bearer stored-license",
                "Content-Type": "application/json",
            },
            timeout=30,
        )
        # The stored blob is verified first to address the request, then the
        # incoming one, then the stored one again for the staleness compare.
        assert call("signed-license") in mock_verify.call_args_list
        mock_upsert.assert_called_once_with(db_session, "signed-license", commit=False)
        mock_publish_cache.assert_called_once_with(payload)

    @pytest.mark.parametrize(
        "license_row",
        [None, MagicMock(license_data="")],
        ids=["no-row", "empty-blob"],
    )
    @patch("ee.onyx.db.license.get_license")
    @patch("ee.onyx.db.license.upsert_license")
    @patch("ee.onyx.utils.license.requests.get")
    def test_returns_none_when_local_reclaim_prereqs_are_missing(
        self,
        mock_get_request: MagicMock,
        mock_upsert: MagicMock,
        mock_get_license: MagicMock,
        license_row: MagicMock | None,
    ) -> None:
        mock_get_license.return_value = license_row

        result = reclaim_license_from_control_plane(MagicMock())

        assert result is None
        mock_get_request.assert_not_called()
        mock_upsert.assert_not_called()


class TestPublishLicenseCache:
    """Runs after the store commits and outside its lock, so it must never
    raise and must yield to a newer entry another writer already published."""

    @patch("ee.onyx.db.license.invalidate_license_cache")
    @patch("ee.onyx.db.license.update_license_cache")
    @patch("ee.onyx.db.license.get_cached_license_metadata", return_value=None)
    @patch("ee.onyx.utils.license.logger")
    def test_write_failure_drops_the_superseded_entry(
        self,
        mock_logger: MagicMock,
        _mock_cached: MagicMock,
        mock_update_cache: MagicMock,
        mock_invalidate: MagicMock,
    ) -> None:
        mock_update_cache.side_effect = RuntimeError("cache failed")

        publish_license_cache(_make_license_payload())

        mock_invalidate.assert_called_once()
        mock_logger.warning.assert_called_once()

    @patch("ee.onyx.db.license.update_license_cache")
    @patch("ee.onyx.db.license.get_cached_license_metadata")
    def test_yields_to_a_newer_cached_entry(
        self, mock_cached: MagicMock, mock_update_cache: MagicMock
    ) -> None:
        payload = _make_license_payload()
        mock_cached.return_value = MagicMock(
            issued_at=payload.issued_at + timedelta(hours=1)
        )

        publish_license_cache(payload)

        mock_update_cache.assert_not_called()


class TestReclaimLicenseFromControlPlaneErrors:
    @patch("ee.onyx.db.license.get_license")
    @patch("ee.onyx.utils.license.verify_license_signature")
    @patch("ee.onyx.db.license.upsert_license")
    @patch("ee.onyx.utils.license.requests.get")
    def test_raises_value_error_when_response_has_no_license_field(
        self,
        mock_get_request: MagicMock,
        mock_upsert: MagicMock,
        mock_verify: MagicMock,
        mock_get_license: MagicMock,
    ) -> None:
        mock_verify.return_value = _make_license_payload()
        mock_get_license.return_value = MagicMock(license_data="stored-license")

        response = MagicMock()
        response.json.return_value = {"tenant_id": "tenant_123"}
        response.raise_for_status = MagicMock()
        mock_get_request.return_value = response

        with pytest.raises(ValueError, match="No license in response"):
            reclaim_license_from_control_plane(MagicMock())

        mock_upsert.assert_not_called()

    @patch("ee.onyx.db.license.get_license")
    @patch("ee.onyx.db.license.get_license_metadata")
    @patch("ee.onyx.db.license.upsert_license")
    @patch("ee.onyx.utils.license.verify_license_signature")
    @patch("ee.onyx.utils.license.requests.get")
    def test_does_not_persist_unverified_license(
        self,
        mock_get_request: MagicMock,
        mock_verify: MagicMock,
        mock_upsert: MagicMock,
        mock_get_metadata: MagicMock,
        mock_get_license: MagicMock,
    ) -> None:
        mock_get_metadata.return_value = MagicMock(tenant_id="tenant_123")
        mock_get_license.return_value = MagicMock(license_data="stored-license")
        mock_verify.side_effect = ValueError("invalid license signature")

        response = MagicMock()
        response.json.return_value = {"license": "signed-license"}
        response.raise_for_status = MagicMock()
        mock_get_request.return_value = response

        with pytest.raises(ValueError, match="invalid license signature"):
            reclaim_license_from_control_plane(MagicMock())

        mock_upsert.assert_not_called()


def _expiring_in(delta: timedelta) -> datetime:
    return datetime.now(timezone.utc) + delta


class TestMaybeScheduleLicenseReclaim:
    @patch("ee.onyx.utils.license.client_app")
    @patch("ee.onyx.utils.license.get_redis_client")
    def test_no_op_when_license_is_outside_the_reclaim_window(
        self,
        mock_get_redis: MagicMock,
        mock_client_app: MagicMock,
    ) -> None:
        maybe_schedule_license_reclaim(
            _expiring_in(LICENSE_RECLAIM_WINDOW + timedelta(days=1)), "tenant_123"
        )

        mock_get_redis.assert_not_called()
        mock_client_app.send_task.assert_not_called()

    @pytest.mark.parametrize(
        "expires_in",
        [timedelta(days=1), timedelta(days=-3)],
        ids=["expiring-soon", "already-expired"],
    )
    @patch("ee.onyx.utils.license.client_app")
    @patch("ee.onyx.utils.license.get_redis_client")
    def test_schedules_one_reclaim_when_debounce_lock_is_acquired(
        self,
        mock_get_redis: MagicMock,
        mock_client_app: MagicMock,
        expires_in: timedelta,
    ) -> None:
        mock_get_redis.return_value.exists.return_value = 0
        mock_get_redis.return_value.set.return_value = True

        maybe_schedule_license_reclaim(_expiring_in(expires_in), "tenant_123")

        mock_client_app.send_task.assert_called_once_with(
            OnyxCeleryTask.RECLAIM_LICENSE,
            kwargs={"tenant_id": "tenant_123"},
            priority=OnyxCeleryPriority.HIGH,
            expires=15 * 60,
        )

    @patch("ee.onyx.utils.license.client_app")
    @patch("ee.onyx.utils.license.get_redis_client")
    def test_reads_the_block_from_the_same_namespace_the_task_writes(
        self,
        mock_get_redis: MagicMock,
        mock_client_app: MagicMock,
    ) -> None:
        """get_redis_client prefixes every key with the tenant it is given, so a
        writer and a reader that disagree on the tenant silently miss each
        other and the block never suppresses anything."""
        mock_get_redis.return_value.get.return_value = license_fingerprint("blob")

        block_license_reclaim("blob")
        assert license_reclaim_is_blocked("blob") is True

        assert mock_get_redis.call_args_list == [call(), call()]
        mock_client_app.send_task.assert_not_called()

    def test_a_block_naming_another_blob_does_not_suppress_this_one(self) -> None:
        """Clearing is best-effort, so a stale block must not outlive the
        license it rejected and stall the replacement for a day."""
        with patch("ee.onyx.utils.license.get_redis_client") as mock_get_redis:
            mock_get_redis.return_value.get.return_value = license_fingerprint("old")
            assert license_reclaim_is_blocked("replacement") is False

    @patch("ee.onyx.utils.license.client_app")
    @patch("ee.onyx.utils.license.get_redis_client")
    def test_no_op_when_debounce_lock_is_held(
        self,
        mock_get_redis: MagicMock,
        mock_client_app: MagicMock,
    ) -> None:
        mock_get_redis.return_value.exists.return_value = 0
        mock_get_redis.return_value.set.return_value = None

        maybe_schedule_license_reclaim(_expiring_in(timedelta(days=1)), "tenant_123")

        mock_client_app.send_task.assert_not_called()

    @patch("ee.onyx.utils.license.client_app")
    @patch("ee.onyx.utils.license.get_redis_client")
    def test_a_held_debounce_is_what_suppresses_a_blocked_license(
        self,
        mock_get_redis: MagicMock,
        mock_client_app: MagicMock,
    ) -> None:
        # The block is keyed to the license blob, which the scheduler does not
        # have. The task widens this debounce instead, so a rejected license
        # stops costing an enqueue per window.
        mock_get_redis.return_value.set.return_value = None

        maybe_schedule_license_reclaim(_expiring_in(timedelta(days=-3)), "tenant_123")

        # SET NX returns None when the key is already held, which is how a
        # widened debounce keeps the blocked license from re-enqueueing.
        mock_get_redis.return_value.set.assert_called_once()
        mock_client_app.send_task.assert_not_called()

    @patch("ee.onyx.utils.license.logger")
    @patch("ee.onyx.utils.license.client_app")
    @patch("ee.onyx.utils.license.get_redis_client")
    def test_scheduling_failure_is_logged_and_swallowed(
        self,
        mock_get_redis: MagicMock,
        mock_client_app: MagicMock,
        mock_logger: MagicMock,
    ) -> None:
        mock_get_redis.side_effect = RuntimeError("redis down")

        maybe_schedule_license_reclaim(_expiring_in(timedelta(days=1)), "tenant_123")

        mock_client_app.send_task.assert_not_called()
        mock_logger.warning.assert_called_once()
