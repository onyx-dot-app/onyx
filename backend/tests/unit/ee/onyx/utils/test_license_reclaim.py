"""Guards the license persistence contract: a blob is stored only after its
signature verifies, and the control-plane re-claim authenticates with the
stored license, validates the response, and persists through the same path.
Also guards the point-of-use scheduler: one debounced reclaim per window,
never an exception into the request that tripped it."""

from collections.abc import Callable, Generator
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, call, patch

import pytest

from ee.onyx.server.license.models import LicensePayload, LicenseSource, PlanType
from ee.onyx.utils.license import (
    LicenseNotStoredError,
    block_license_reclaim,
    license_fingerprint,
    license_reclaim_is_blocked,
    maybe_schedule_license_reclaim,
    publish_license_cache,
    reclaim_license_from_control_plane,
    verify_and_store_license,
)
from ee.onyx.utils.license_expiry import LICENSE_RECLAIM_WINDOW
from onyx.cache.interface import CacheBackendType
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
    """Source is derived from the payload, so every writer computes the same
    value."""

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
        mock_publish_cache.assert_called_once_with(db_session)

    @patch("ee.onyx.utils.license.publish_license_cache")
    @patch("ee.onyx.db.license.get_license")
    @patch("ee.onyx.db.license.upsert_license")
    @patch("ee.onyx.utils.license.verify_license_signature")
    def test_discarding_an_older_license_still_reconciles_the_cache(
        self,
        mock_verify: MagicMock,
        mock_upsert: MagicMock,
        mock_get_license: MagicMock,
        mock_publish_cache: MagicMock,
    ) -> None:
        """Sync is what a user clicks to clear staleness, so reporting success
        over a stale entry makes the button useless when it is most needed."""
        incoming = _make_license_payload()
        newer = _make_license_payload()
        newer.issued_at = incoming.issued_at + timedelta(hours=1)
        mock_get_license.return_value = MagicMock(license_data="stored-license")
        mock_verify.side_effect = lambda blob: (
            newer if blob == "stored-license" else incoming
        )

        db_session = MagicMock()
        result = verify_and_store_license(db_session, "older-license")

        assert result == incoming
        mock_upsert.assert_not_called()
        mock_publish_cache.assert_called_once_with(db_session)

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

    @patch("ee.onyx.db.license.update_license_cache")
    @patch("ee.onyx.db.license.get_cached_license_metadata", return_value=None)
    @patch("ee.onyx.db.license.get_cache_backend")
    @patch("ee.onyx.db.license.upsert_license")
    @patch("ee.onyx.utils.license.verify_license_signature")
    def test_publishes_into_the_namespace_readers_resolve(
        self,
        mock_verify: MagicMock,
        _mock_upsert: MagicMock,
        mock_get_cache: MagicMock,
        _mock_cached: MagicMock,
        _mock_update_cache: MagicMock,
    ) -> None:
        """The license carries the tenant id the control plane assigned, which
        is not the one an ambient read resolves. Publishing under it strands the
        fresh entry and a sync appears to do nothing."""
        from ee.onyx.db.license import get_license_metadata

        lock = mock_get_cache.return_value.lock.return_value
        lock.acquire.return_value = True
        lock.owned.return_value = True
        mock_verify.return_value = _make_license_payload()

        verify_and_store_license(MagicMock(), "signed-license")
        written = [c.kwargs.get("tenant_id") for c in mock_get_cache.call_args_list]

        mock_get_cache.reset_mock()
        get_license_metadata(MagicMock())
        read = [c.kwargs.get("tenant_id") for c in mock_get_cache.call_args_list]

        assert written and read
        assert set(written) == set(read)


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
        mock_publish_cache.assert_called_once_with(db_session)

    @pytest.mark.parametrize(
        "license_row",
        [None, MagicMock(license_data="")],
        ids=["no-row", "empty-blob"],
    )
    @patch("ee.onyx.db.license.get_license")
    @patch("ee.onyx.db.license.upsert_license")
    @patch("ee.onyx.utils.license.requests.get")
    def test_raises_when_there_is_nothing_to_authenticate_with(
        self,
        mock_get_request: MagicMock,
        mock_upsert: MagicMock,
        mock_get_license: MagicMock,
        license_row: MagicMock | None,
    ) -> None:
        """Distinct from a rejection: nothing stored is a checkout problem, a
        rejection is a replace-your-license problem, and the admin is told
        different things."""
        mock_get_license.return_value = license_row

        with pytest.raises(LicenseNotStoredError):
            reclaim_license_from_control_plane(MagicMock())

        mock_get_request.assert_not_called()
        mock_upsert.assert_not_called()


class TestPublishLicenseCache:
    """Runs after the store commits and outside its lock, so it must never
    raise and must converge on current row state."""

    @pytest.fixture(autouse=True)
    def _cache_backend(self) -> Generator[MagicMock, None, None]:
        with patch("ee.onyx.db.license.get_cache_backend") as mock_get_cache:
            lock = mock_get_cache.return_value.lock.return_value
            lock.acquire.return_value = True
            lock.owned.return_value = True
            yield mock_get_cache

    @pytest.fixture(autouse=True)
    def _row_present(self) -> Generator[MagicMock, None, None]:
        with patch("ee.onyx.db.license.get_license") as mock_get_license:
            mock_get_license.return_value = MagicMock(license_data="blob")
            yield mock_get_license

    @pytest.fixture(autouse=True)
    def _row_payload(self) -> Generator[MagicMock, None, None]:
        with patch("ee.onyx.utils.license.verify_license_signature") as mock_verify:
            mock_verify.return_value = _make_license_payload()
            yield mock_verify

    @patch("ee.onyx.db.license.invalidate_license_cache")
    @patch("ee.onyx.db.license.update_license_cache")
    @patch("ee.onyx.utils.license.logger")
    def test_write_failure_drops_the_superseded_entry(
        self,
        mock_logger: MagicMock,
        mock_update_cache: MagicMock,
        mock_invalidate: MagicMock,
    ) -> None:
        mock_update_cache.side_effect = RuntimeError("cache failed")

        publish_license_cache(MagicMock())

        mock_invalidate.assert_called_once()
        mock_logger.warning.assert_called_once()

    @patch("ee.onyx.db.license.update_license_cache")
    @patch("ee.onyx.db.license.get_cached_license_metadata")
    def test_row_state_wins_over_a_cached_entry_claiming_a_later_issue(
        self,
        mock_cached: MagicMock,
        mock_update_cache: MagicMock,
        _row_payload: MagicMock,
    ) -> None:
        """The row is the entitlement, so an entry that outruns it is wrong
        rather than authoritative. Deferring to it strands enforcement on a
        license the instance does not hold until the TTL expires."""
        row_payload = _row_payload.return_value
        mock_cached.return_value = MagicMock(
            issued_at=row_payload.issued_at + timedelta(hours=1)
        )

        publish_license_cache(MagicMock())

        mock_update_cache.assert_called_once()
        assert mock_update_cache.call_args.args[0] is row_payload

    @patch("ee.onyx.db.license.update_license_cache")
    def test_publishes_current_row_state(
        self,
        mock_update_cache: MagicMock,
        _row_payload: MagicMock,
    ) -> None:
        """The entry derives from the row re-read under the lock, so a slow
        publisher advertises its overtaker's license rather than its own."""
        publish_license_cache(MagicMock())

        assert mock_update_cache.call_args.args[0] is _row_payload.return_value

    @patch("ee.onyx.db.license.update_license_cache")
    def test_the_compare_and_write_is_serialized(
        self,
        mock_update_cache: MagicMock,
        _cache_backend: MagicMock,
    ) -> None:
        """Two writers reading the cache before either writes would otherwise
        publish in the opposite order to the one they committed in."""
        lock = _cache_backend.return_value.lock.return_value

        publish_license_cache(MagicMock())

        mock_update_cache.assert_called_once()
        lock.acquire.assert_called_once()
        lock.release.assert_called_once()

    @pytest.mark.parametrize(
        "unavailable",
        [
            pytest.param(
                lambda lock: setattr(lock, "acquire", MagicMock(return_value=False)),
                id="contended",
            ),
            pytest.param(
                lambda lock: setattr(
                    lock, "acquire", MagicMock(side_effect=RuntimeError("no conn"))
                ),
                id="raises",
            ),
        ],
    )
    @patch("ee.onyx.db.license.build_license_metadata")
    @patch("ee.onyx.db.license.update_license_cache")
    def test_an_unavailable_lock_serves_without_caching(
        self,
        mock_update_cache: MagicMock,
        mock_build: MagicMock,
        unavailable: Callable[[MagicMock], None],
        _cache_backend: MagicMock,
    ) -> None:
        """An unserialized write can overwrite a newer entry or resurrect a
        deleted one, so the caller gets its metadata and the cache stays
        untouched until a locked publish lands."""
        mock_build.return_value = (MagicMock(), 60)
        lock = _cache_backend.return_value.lock.return_value
        unavailable(lock)

        publish_license_cache(MagicMock())

        mock_build.assert_called_once()
        mock_update_cache.assert_not_called()
        lock.release.assert_not_called()

    @patch("ee.onyx.db.license.invalidate_license_cache")
    @patch("ee.onyx.db.license.update_license_cache")
    def test_a_deleted_row_is_not_resurrected(
        self,
        mock_update_cache: MagicMock,
        mock_invalidate: MagicMock,
        _row_present: MagicMock,
    ) -> None:
        """A writer that committed just before a delete must not publish an
        entry for the row the delete removed."""
        _row_present.return_value = None

        publish_license_cache(MagicMock())

        mock_update_cache.assert_not_called()
        mock_invalidate.assert_called_once()

    @patch("ee.onyx.db.license.invalidate_license_cache")
    @patch("ee.onyx.db.license.update_license_cache")
    def test_a_lost_lease_drops_the_entry(
        self,
        mock_update_cache: MagicMock,
        mock_invalidate: MagicMock,
        _cache_backend: MagicMock,
    ) -> None:
        """A write that outlived its lease may have raced a delete's
        invalidate, so a dropped entry beats a possibly-resurrected one."""
        lock = _cache_backend.return_value.lock.return_value
        lock.owned.side_effect = [False, False]

        publish_license_cache(MagicMock())

        mock_update_cache.assert_called_once()
        mock_invalidate.assert_called_once()


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
    @patch("ee.onyx.utils.license.CACHE_BACKEND", CacheBackendType.POSTGRES)
    @patch("ee.onyx.utils.license.client_app")
    @patch("ee.onyx.utils.license.get_redis_client")
    def test_no_op_without_redis(
        self,
        mock_get_redis: MagicMock,
        mock_client_app: MagicMock,
    ) -> None:
        """The debounce and the Celery broker are both this Redis, so where it
        does not exist every request in the window would log a failed connect
        for a send that can never be consumed."""
        maybe_schedule_license_reclaim(_expiring_in(timedelta(days=1)), "tenant_123")

        mock_get_redis.assert_not_called()
        mock_client_app.send_task.assert_not_called()

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
        ("expires_in", "expected_debounce"),
        [
            (timedelta(days=1), 15 * 60),
            (timedelta(minutes=30), 60),
            (timedelta(days=-3), 60),
        ],
        ids=["expiring-soon", "period-ending", "already-expired"],
    )
    @patch("ee.onyx.utils.license.client_app")
    @patch("ee.onyx.utils.license.get_redis_client")
    def test_schedules_one_reclaim_when_debounce_lock_is_acquired(
        self,
        mock_get_redis: MagicMock,
        mock_client_app: MagicMock,
        expires_in: timedelta,
        expected_debounce: int,
    ) -> None:
        """Once the period is ending the replacement is expected imminently, so
        a served request is the earliest chance to fetch it and the debounce
        tightens. Holding the full window there would strand a renewed customer
        on an expired license until the next beat."""
        mock_get_redis.return_value.exists.return_value = 0
        mock_get_redis.return_value.set.return_value = True

        maybe_schedule_license_reclaim(_expiring_in(expires_in), "tenant_123")

        assert mock_get_redis.return_value.set.call_args.kwargs["ex"] == (
            expected_debounce
        )
        mock_client_app.send_task.assert_called_once_with(
            OnyxCeleryTask.RECLAIM_LICENSE,
            kwargs={"tenant_id": "tenant_123"},
            priority=OnyxCeleryPriority.HIGH,
            expires=expected_debounce,
        )

    @patch("ee.onyx.utils.license.get_cache_backend")
    def test_reads_the_block_from_the_same_namespace_the_task_writes(
        self,
        mock_get_cache: MagicMock,
    ) -> None:
        """The backend prefixes every key with the tenant it is given, so a
        writer and a reader that disagree on the tenant silently miss each
        other and the block never suppresses anything."""
        mock_get_cache.return_value.get.return_value = license_fingerprint(
            "blob"
        ).encode()

        block_license_reclaim("blob")
        assert license_reclaim_is_blocked("blob") is True

        assert mock_get_cache.call_args_list == [call(), call()]

    @patch("ee.onyx.utils.license.get_cache_backend")
    def test_a_block_naming_another_blob_does_not_suppress_this_one(
        self, mock_get_cache: MagicMock
    ) -> None:
        """Clearing is best-effort, so a stale block must not outlive the
        license it rejected and stall the replacement for a day."""
        mock_get_cache.return_value.get.return_value = license_fingerprint(
            "old"
        ).encode()
        assert license_reclaim_is_blocked("replacement") is False

    @patch("ee.onyx.utils.license.get_cache_backend")
    def test_the_block_survives_a_deployment_without_redis(
        self, mock_get_cache: MagicMock
    ) -> None:
        """Onyx Lite runs no Redis at all, and a block that silently no-ops
        there would re-send a rejected credential every poll interval."""
        mock_get_cache.return_value.get.return_value = None

        assert license_reclaim_is_blocked("blob") is False
        mock_get_cache.return_value.get.assert_called_once()

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
