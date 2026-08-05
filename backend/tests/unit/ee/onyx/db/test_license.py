"""Tests for license database CRUD operations."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from ee.onyx.db.license import (
    check_seat_availability,
    delete_license,
    get_license,
    get_used_seats,
    refresh_license_cache,
    upsert_license,
)
from ee.onyx.server.license.models import LicenseMetadata, LicenseSource, PlanType
from onyx.db.models import License
from onyx.server.settings.models import ApplicationStatus


class TestGetLicense:
    """Tests for get_license function."""

    def test_get_existing_license(self) -> None:
        """Test getting an existing license."""
        mock_session = MagicMock()
        mock_license = License(id=1, license_data="test_data")

        # Mock the query chain
        mock_session.execute.return_value.scalars.return_value.first.return_value = (
            mock_license
        )

        result = get_license(mock_session)

        assert result is not None
        assert result.license_data == "test_data"
        mock_session.execute.assert_called_once()

    def test_get_no_license(self) -> None:
        """Test getting when no license exists."""
        mock_session = MagicMock()
        mock_session.execute.return_value.scalars.return_value.first.return_value = None

        result = get_license(mock_session)

        assert result is None


class TestUpsertLicense:
    """Tests for upsert_license function."""

    def test_insert_new_license(self) -> None:
        """Test inserting a new license when none exists."""
        mock_session = MagicMock()
        mock_session.execute.return_value.scalars.return_value.first.return_value = None

        upsert_license(mock_session, "new_license_data")

        # Verify add was called with a License object
        mock_session.add.assert_called_once()
        added_license = mock_session.add.call_args[0][0]
        assert isinstance(added_license, License)
        assert added_license.license_data == "new_license_data"

        mock_session.commit.assert_called_once()
        mock_session.refresh.assert_called_once()

    def test_update_existing_license(self) -> None:
        """Test updating an existing license."""
        mock_session = MagicMock()
        existing_license = License(id=1, license_data="old_data")
        mock_session.execute.return_value.scalars.return_value.first.return_value = (
            existing_license
        )

        upsert_license(mock_session, "updated_license_data")

        # Verify the existing license was updated
        assert existing_license.license_data == "updated_license_data"
        mock_session.add.assert_not_called()  # Should not add new
        mock_session.commit.assert_called_once()
        mock_session.refresh.assert_called_once_with(existing_license)


class TestDeleteLicense:
    """Tests for delete_license function."""

    def test_delete_existing_license(self) -> None:
        """Test deleting an existing license."""
        mock_session = MagicMock()
        existing_license = License(id=1, license_data="test_data")
        mock_session.execute.return_value.scalars.return_value.first.return_value = (
            existing_license
        )

        result = delete_license(mock_session)

        assert result is True
        mock_session.delete.assert_called_once_with(existing_license)
        mock_session.commit.assert_called_once()

    def test_delete_no_license(self) -> None:
        """Test deleting when no license exists."""
        mock_session = MagicMock()
        mock_session.execute.return_value.scalars.return_value.first.return_value = None

        result = delete_license(mock_session)

        assert result is False
        mock_session.delete.assert_not_called()
        mock_session.commit.assert_not_called()


def _make_license_metadata(seats: int = 10) -> LicenseMetadata:
    now = datetime.now(timezone.utc)
    return LicenseMetadata(
        tenant_id="public",
        seats=seats,
        used_seats=0,
        plan_type=PlanType.ANNUAL,
        issued_at=now,
        expires_at=now + timedelta(days=365),
        status=ApplicationStatus.ACTIVE,
        source=LicenseSource.MANUAL_UPLOAD,
    )


class TestCheckSeatAvailabilitySelfHosted:
    """Seat checks for self-hosted (MULTI_TENANT=False)."""

    @patch("ee.onyx.db.license.get_license_metadata", return_value=None)
    def test_no_license_means_unlimited(self, _mock_meta: MagicMock) -> None:
        result = check_seat_availability(MagicMock(), seats_needed=1)
        assert result.available is True

    @patch("ee.onyx.db.license.get_used_seats", return_value=5)
    @patch("ee.onyx.db.license.get_license_metadata")
    def test_seats_available(self, mock_meta: MagicMock, _mock_used: MagicMock) -> None:
        mock_meta.return_value = _make_license_metadata(seats=10)
        result = check_seat_availability(MagicMock(), seats_needed=1)
        assert result.available is True

    @patch("ee.onyx.db.license.get_used_seats", return_value=10)
    @patch("ee.onyx.db.license.get_license_metadata")
    def test_seats_full_blocks_creation(
        self, mock_meta: MagicMock, _mock_used: MagicMock
    ) -> None:
        mock_meta.return_value = _make_license_metadata(seats=10)
        result = check_seat_availability(MagicMock(), seats_needed=1)
        assert result.available is False
        assert result.error_message is not None
        assert "10 of 10" in result.error_message

    @patch("ee.onyx.db.license.get_used_seats", return_value=10)
    @patch("ee.onyx.db.license.get_license_metadata")
    def test_exactly_at_capacity_allows_no_more(
        self, mock_meta: MagicMock, _mock_used: MagicMock
    ) -> None:
        """Filling to 100% is allowed; exceeding is not."""
        mock_meta.return_value = _make_license_metadata(seats=10)
        result = check_seat_availability(MagicMock(), seats_needed=1)
        assert result.available is False

    @patch("ee.onyx.db.license.get_used_seats", return_value=9)
    @patch("ee.onyx.db.license.get_license_metadata")
    def test_filling_to_capacity_is_allowed(
        self, mock_meta: MagicMock, _mock_used: MagicMock
    ) -> None:
        mock_meta.return_value = _make_license_metadata(seats=10)
        result = check_seat_availability(MagicMock(), seats_needed=1)
        assert result.available is True


class TestCheckSeatAvailabilityMultiTenant:
    """Seat checks for multi-tenant cloud (MULTI_TENANT=True).

    Verifies that get_used_seats takes the MULTI_TENANT branch
    and delegates to get_tenant_count.
    """

    @patch("ee.onyx.db.license.MULTI_TENANT", True)
    @patch(
        "ee.onyx.db.user_tenant_mapping.get_tenant_count",
        return_value=5,
    )
    @patch("ee.onyx.db.license.get_license_metadata")
    def test_seats_available_multi_tenant(
        self,
        mock_meta: MagicMock,
        mock_tenant_count: MagicMock,
    ) -> None:
        mock_meta.return_value = _make_license_metadata(seats=10)
        result = check_seat_availability(
            MagicMock(), seats_needed=1, tenant_id="tenant-abc"
        )
        assert result.available is True
        mock_tenant_count.assert_called_once_with("tenant-abc")

    @patch("ee.onyx.db.license.MULTI_TENANT", True)
    @patch(
        "ee.onyx.db.user_tenant_mapping.get_tenant_count",
        return_value=10,
    )
    @patch("ee.onyx.db.license.get_license_metadata")
    def test_seats_full_multi_tenant(
        self,
        mock_meta: MagicMock,
        mock_tenant_count: MagicMock,
    ) -> None:
        mock_meta.return_value = _make_license_metadata(seats=10)
        result = check_seat_availability(
            MagicMock(), seats_needed=1, tenant_id="tenant-abc"
        )
        assert result.available is False
        assert result.error_message is not None
        mock_tenant_count.assert_called_once_with("tenant-abc")


class TestGetUsedSeatsAccountTypeFiltering:
    """Verify get_used_seats query excludes SERVICE_ACCOUNT but includes BOT."""

    @patch("ee.onyx.db.license.MULTI_TENANT", False)
    @patch("onyx.db.engine.sql_engine.get_session_with_current_tenant")
    def test_excludes_service_accounts(self, mock_get_session: MagicMock) -> None:
        """SERVICE_ACCOUNT users should not count toward seats."""
        mock_session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)
        mock_session.execute.return_value.scalar.return_value = 5

        result = get_used_seats()

        assert result == 5
        # Inspect the compiled query to verify account_type filter
        call_args = mock_session.execute.call_args
        query = call_args[0][0]
        compiled = str(query.compile(compile_kwargs={"literal_binds": True}))
        assert "SERVICE_ACCOUNT" in compiled
        # BOT should NOT be excluded
        assert "BOT" not in compiled

    @patch("ee.onyx.db.license.MULTI_TENANT", False)
    @patch("onyx.db.engine.sql_engine.get_session_with_current_tenant")
    def test_still_excludes_ext_perm_user(self, mock_get_session: MagicMock) -> None:
        """EXT_PERM_USER exclusion should still be present."""
        mock_session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)
        mock_session.execute.return_value.scalar.return_value = 3

        get_used_seats()

        call_args = mock_session.execute.call_args
        query = call_args[0][0]
        compiled = str(query.compile(compile_kwargs={"literal_binds": True}))
        assert "EXT_PERM_USER" in compiled


class TestRefreshLicenseCacheLocking:
    """refresh_license_cache runs on async request paths, so it must never
    sleep on the cache lock."""

    @patch("ee.onyx.db.license.update_license_cache")
    @patch("ee.onyx.db.license.get_cache_backend")
    @patch("ee.onyx.utils.license.verify_license_signature")
    def test_refresh_never_waits_on_the_cache_lock(
        self,
        mock_verify: MagicMock,
        mock_get_cache: MagicMock,
        mock_update_cache: MagicMock,
    ) -> None:
        lock = mock_get_cache.return_value.lock.return_value
        lock.acquire.return_value = True
        mock_verify.return_value = MagicMock(issued_at=datetime.now(timezone.utc))

        db_session = MagicMock()
        db_session.execute.return_value.scalars.return_value.first.return_value = (
            License(license_data="signed")
        )

        refresh_license_cache(db_session)

        lock.acquire.assert_called_once_with(blocking=False, blocking_timeout=None)
        mock_update_cache.assert_called_once()


class TestStoreLockDiscipline:
    """The advisory lock and the post-lock expiry are what keep a slower
    store from overwriting a newer license it never saw."""

    @patch("ee.onyx.utils.license.publish_license_cache")
    @patch("ee.onyx.utils.license.resume_license_reclaim")
    @patch("ee.onyx.db.license.upsert_license")
    @patch("ee.onyx.db.license.get_license", return_value=None)
    @patch("ee.onyx.db.license.acquire_license_store_lock")
    @patch("ee.onyx.utils.license.verify_license_signature")
    def test_store_locks_then_expires_before_reading(
        self,
        mock_verify: MagicMock,
        mock_lock: MagicMock,
        mock_get_license: MagicMock,
        _mock_upsert: MagicMock,
        _mock_resume: MagicMock,
        _mock_publish: MagicMock,
    ) -> None:
        from ee.onyx.utils.license import verify_and_store_license

        mock_verify.return_value = MagicMock(tenant_id="t1")
        db_session = MagicMock()
        order = MagicMock()
        order.attach_mock(mock_lock, "lock")
        order.attach_mock(db_session.expire_all, "expire_all")
        order.attach_mock(mock_get_license, "read")

        verify_and_store_license(db_session, "blob")

        assert [c[0] for c in order.mock_calls[:3]] == [
            "lock",
            "expire_all",
            "read",
        ]

    @patch("ee.onyx.db.license._license_cache_lock")
    @patch("ee.onyx.db.license.invalidate_license_cache")
    @patch("ee.onyx.db.license.acquire_license_store_lock")
    def test_delete_invalidates_under_the_cache_lock(
        self,
        _mock_store_lock: MagicMock,
        mock_invalidate: MagicMock,
        mock_cache_lock: MagicMock,
    ) -> None:
        """Unserialized, a store that committed just before the delete can
        publish its entry after this invalidate."""
        db_session = MagicMock()
        db_session.execute.return_value.scalars.return_value.first.return_value = (
            License(license_data="blob")
        )

        assert delete_license(db_session) is True

        mock_cache_lock.assert_called_once()
        mock_invalidate.assert_called_once()


class TestCacheTtlBoundaryCap:
    """The cached status is computed at write time, so an entry must not
    outlive the boundary that would change it."""

    @patch("ee.onyx.db.license.get_used_seats", return_value=1)
    @patch("ee.onyx.db.license.get_cache_backend")
    def test_ttl_stops_at_license_expiry(
        self, mock_get_cache: MagicMock, _mock_seats: MagicMock
    ) -> None:
        from ee.onyx.db.license import update_license_cache

        payload = MagicMock(
            tenant_id="t1",
            organization_name="o",
            seats=5,
            plan_type="monthly",
            issued_at=datetime.now(timezone.utc) - timedelta(days=1),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=3),
            stripe_subscription_id=None,
            customer_tier=None,
            source=LicenseSource.AUTO_FETCH,
        )

        update_license_cache(payload)

        ttl = mock_get_cache.return_value.set.call_args.kwargs["ex"]
        assert 60 <= ttl <= 3 * 3600 + 2

    @patch("ee.onyx.db.license.get_used_seats", return_value=1)
    @patch("ee.onyx.db.license.get_cache_backend")
    def test_far_expiry_keeps_the_default_ttl(
        self, mock_get_cache: MagicMock, _mock_seats: MagicMock
    ) -> None:
        from ee.onyx.db.license import LICENSE_CACHE_TTL_SECONDS, update_license_cache

        payload = MagicMock(
            tenant_id="t1",
            organization_name="o",
            seats=5,
            plan_type="monthly",
            issued_at=datetime.now(timezone.utc) - timedelta(days=1),
            expires_at=datetime.now(timezone.utc) + timedelta(days=90),
            stripe_subscription_id=None,
            customer_tier=None,
            source=LicenseSource.AUTO_FETCH,
        )

        update_license_cache(payload)

        ttl = mock_get_cache.return_value.set.call_args.kwargs["ex"]
        assert ttl == LICENSE_CACHE_TTL_SECONDS
