"""Tests for license database CRUD operations."""

from datetime import datetime
from datetime import timedelta
from datetime import timezone
from unittest.mock import MagicMock
from unittest.mock import patch

from ee.onyx.db.license import check_seat_availability
from ee.onyx.db.license import delete_license
from ee.onyx.db.license import get_license
from ee.onyx.db.license import upsert_license
from ee.onyx.server.license.models import LicenseMetadata
from ee.onyx.server.license.models import LicenseSource
from ee.onyx.server.license.models import PlanType
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
        "ee.onyx.server.tenants.user_mapping.get_tenant_count",
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
        "ee.onyx.server.tenants.user_mapping.get_tenant_count",
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
