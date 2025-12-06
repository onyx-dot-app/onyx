"""Tests for license database CRUD operations."""

from unittest.mock import MagicMock

from ee.onyx.db.license import delete_license
from ee.onyx.db.license import get_license
from ee.onyx.db.license import upsert_license
from onyx.db.models import License


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
