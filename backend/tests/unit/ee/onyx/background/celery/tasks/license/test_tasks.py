"""Tests for license refresh Celery task."""

from datetime import datetime
from datetime import timezone
from unittest.mock import MagicMock
from unittest.mock import patch

import requests

from ee.onyx.background.celery.tasks.license.tasks import _refresh_from_database
from ee.onyx.background.celery.tasks.license.tasks import license_refresh_task
from ee.onyx.server.license.models import LicensePayload
from ee.onyx.server.license.models import PlanType


def create_mock_payload(tenant_id: str = "tenant_123") -> LicensePayload:
    """Create a mock license payload for testing."""
    return LicensePayload(
        version="1.0",
        tenant_id=tenant_id,
        issued_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        expires_at=datetime(2025, 12, 31, tzinfo=timezone.utc),
        seats=50,
        plan_type=PlanType.MONTHLY,
    )


class TestLicenseRefreshTask:
    """Tests for license_refresh_task function."""

    def test_successful_refresh(self) -> None:
        """Test successful license refresh from control plane."""
        mock_payload = create_mock_payload()

        with (
            patch(
                "ee.onyx.background.celery.tasks.license.tasks.get_current_tenant_id"
            ) as mock_get_tenant,
            patch(
                "ee.onyx.background.celery.tasks.license.tasks.generate_data_plane_token"
            ) as mock_token,
            patch(
                "ee.onyx.background.celery.tasks.license.tasks.requests.get"
            ) as mock_get,
            patch(
                "ee.onyx.background.celery.tasks.license.tasks.verify_license_signature"
            ) as mock_verify,
            patch(
                "ee.onyx.background.celery.tasks.license.tasks.get_session_with_current_tenant"
            ) as mock_session,
            patch(
                "ee.onyx.background.celery.tasks.license.tasks.upsert_license"
            ) as mock_upsert,
            patch(
                "ee.onyx.background.celery.tasks.license.tasks.update_license_cache"
            ) as mock_update_cache,
            patch(
                "ee.onyx.background.celery.tasks.license.tasks.CONTROL_PLANE_API_BASE_URL",
                "https://control.example.com",
            ),
        ):
            mock_get_tenant.return_value = "tenant_123"
            mock_token.return_value = "test_token"

            mock_response = MagicMock()
            mock_response.json.return_value = {"license": "encoded_license_data"}
            mock_get.return_value = mock_response

            mock_verify.return_value = mock_payload
            mock_session.return_value.__enter__ = MagicMock()
            mock_session.return_value.__exit__ = MagicMock()

            result = license_refresh_task()

            assert result is True
            mock_token.assert_called_once()
            mock_get.assert_called_once()
            mock_verify.assert_called_once_with("encoded_license_data")
            mock_upsert.assert_called_once()
            mock_update_cache.assert_called_once()

    def test_no_data_plane_secret(self) -> None:
        """Test fallback when DATA_PLANE_SECRET is not configured."""
        with (
            patch(
                "ee.onyx.background.celery.tasks.license.tasks.get_current_tenant_id"
            ) as mock_get_tenant,
            patch(
                "ee.onyx.background.celery.tasks.license.tasks.generate_data_plane_token"
            ) as mock_token,
            patch(
                "ee.onyx.background.celery.tasks.license.tasks._refresh_from_database"
            ) as mock_refresh_db,
        ):
            mock_get_tenant.return_value = "tenant_123"
            mock_token.side_effect = ValueError("DATA_PLANE_SECRET not set")

            result = license_refresh_task()

            assert result is False
            mock_refresh_db.assert_called_once_with("tenant_123")

    def test_http_error_from_control_plane(self) -> None:
        """Test fallback when control plane returns HTTP error."""
        with (
            patch(
                "ee.onyx.background.celery.tasks.license.tasks.get_current_tenant_id"
            ) as mock_get_tenant,
            patch(
                "ee.onyx.background.celery.tasks.license.tasks.generate_data_plane_token"
            ) as mock_token,
            patch(
                "ee.onyx.background.celery.tasks.license.tasks.requests.get"
            ) as mock_get,
            patch(
                "ee.onyx.background.celery.tasks.license.tasks._refresh_from_database"
            ) as mock_refresh_db,
            patch(
                "ee.onyx.background.celery.tasks.license.tasks.CONTROL_PLANE_API_BASE_URL",
                "https://control.example.com",
            ),
        ):
            mock_get_tenant.return_value = "tenant_123"
            mock_token.return_value = "test_token"

            mock_response = MagicMock()
            mock_response.status_code = 500
            mock_response.raise_for_status.side_effect = requests.HTTPError(
                response=mock_response
            )
            mock_get.return_value = mock_response

            result = license_refresh_task()

            assert result is False
            mock_refresh_db.assert_called_once_with("tenant_123")

    def test_connection_error(self) -> None:
        """Test fallback when control plane is unreachable."""
        with (
            patch(
                "ee.onyx.background.celery.tasks.license.tasks.get_current_tenant_id"
            ) as mock_get_tenant,
            patch(
                "ee.onyx.background.celery.tasks.license.tasks.generate_data_plane_token"
            ) as mock_token,
            patch(
                "ee.onyx.background.celery.tasks.license.tasks.requests.get"
            ) as mock_get,
            patch(
                "ee.onyx.background.celery.tasks.license.tasks._refresh_from_database"
            ) as mock_refresh_db,
            patch(
                "ee.onyx.background.celery.tasks.license.tasks.CONTROL_PLANE_API_BASE_URL",
                "https://control.example.com",
            ),
        ):
            mock_get_tenant.return_value = "tenant_123"
            mock_token.return_value = "test_token"
            mock_get.side_effect = requests.RequestException("Connection refused")

            result = license_refresh_task()

            assert result is False
            mock_refresh_db.assert_called_once_with("tenant_123")

    def test_license_verification_failed(self) -> None:
        """Test fallback when license signature verification fails."""
        with (
            patch(
                "ee.onyx.background.celery.tasks.license.tasks.get_current_tenant_id"
            ) as mock_get_tenant,
            patch(
                "ee.onyx.background.celery.tasks.license.tasks.generate_data_plane_token"
            ) as mock_token,
            patch(
                "ee.onyx.background.celery.tasks.license.tasks.requests.get"
            ) as mock_get,
            patch(
                "ee.onyx.background.celery.tasks.license.tasks.verify_license_signature"
            ) as mock_verify,
            patch(
                "ee.onyx.background.celery.tasks.license.tasks._refresh_from_database"
            ) as mock_refresh_db,
            patch(
                "ee.onyx.background.celery.tasks.license.tasks.CONTROL_PLANE_API_BASE_URL",
                "https://control.example.com",
            ),
        ):
            mock_get_tenant.return_value = "tenant_123"
            mock_token.return_value = "test_token"

            mock_response = MagicMock()
            mock_response.json.return_value = {"license": "invalid_license"}
            mock_get.return_value = mock_response

            mock_verify.side_effect = ValueError("Invalid license signature")

            result = license_refresh_task()

            assert result is False
            mock_refresh_db.assert_called_once_with("tenant_123")

    def test_tenant_id_mismatch(self) -> None:
        """Test fallback when license tenant ID doesn't match."""
        mock_payload = create_mock_payload(tenant_id="different_tenant")

        with (
            patch(
                "ee.onyx.background.celery.tasks.license.tasks.get_current_tenant_id"
            ) as mock_get_tenant,
            patch(
                "ee.onyx.background.celery.tasks.license.tasks.generate_data_plane_token"
            ) as mock_token,
            patch(
                "ee.onyx.background.celery.tasks.license.tasks.requests.get"
            ) as mock_get,
            patch(
                "ee.onyx.background.celery.tasks.license.tasks.verify_license_signature"
            ) as mock_verify,
            patch(
                "ee.onyx.background.celery.tasks.license.tasks._refresh_from_database"
            ) as mock_refresh_db,
            patch(
                "ee.onyx.background.celery.tasks.license.tasks.CONTROL_PLANE_API_BASE_URL",
                "https://control.example.com",
            ),
        ):
            mock_get_tenant.return_value = "tenant_123"
            mock_token.return_value = "test_token"

            mock_response = MagicMock()
            mock_response.json.return_value = {"license": "encoded_license_data"}
            mock_get.return_value = mock_response

            mock_verify.return_value = mock_payload

            result = license_refresh_task()

            assert result is False
            mock_refresh_db.assert_called_once_with("tenant_123")

    def test_invalid_response_missing_license_key(self) -> None:
        """Test fallback when response doesn't contain license key."""
        with (
            patch(
                "ee.onyx.background.celery.tasks.license.tasks.get_current_tenant_id"
            ) as mock_get_tenant,
            patch(
                "ee.onyx.background.celery.tasks.license.tasks.generate_data_plane_token"
            ) as mock_token,
            patch(
                "ee.onyx.background.celery.tasks.license.tasks.requests.get"
            ) as mock_get,
            patch(
                "ee.onyx.background.celery.tasks.license.tasks._refresh_from_database"
            ) as mock_refresh_db,
            patch(
                "ee.onyx.background.celery.tasks.license.tasks.CONTROL_PLANE_API_BASE_URL",
                "https://control.example.com",
            ),
        ):
            mock_get_tenant.return_value = "tenant_123"
            mock_token.return_value = "test_token"

            mock_response = MagicMock()
            mock_response.json.return_value = {"other_key": "value"}
            mock_get.return_value = mock_response

            result = license_refresh_task()

            assert result is False
            mock_refresh_db.assert_called_once_with("tenant_123")

    def test_empty_license_data(self) -> None:
        """Test fallback when license data is empty/null."""
        with (
            patch(
                "ee.onyx.background.celery.tasks.license.tasks.get_current_tenant_id"
            ) as mock_get_tenant,
            patch(
                "ee.onyx.background.celery.tasks.license.tasks.generate_data_plane_token"
            ) as mock_token,
            patch(
                "ee.onyx.background.celery.tasks.license.tasks.requests.get"
            ) as mock_get,
            patch(
                "ee.onyx.background.celery.tasks.license.tasks._refresh_from_database"
            ) as mock_refresh_db,
            patch(
                "ee.onyx.background.celery.tasks.license.tasks.CONTROL_PLANE_API_BASE_URL",
                "https://control.example.com",
            ),
        ):
            mock_get_tenant.return_value = "tenant_123"
            mock_token.return_value = "test_token"

            mock_response = MagicMock()
            mock_response.json.return_value = {"license": None}
            mock_get.return_value = mock_response

            result = license_refresh_task()

            assert result is False
            mock_refresh_db.assert_called_once_with("tenant_123")

    def test_uses_passed_tenant_id(self) -> None:
        """Test that passed tenant_id is used instead of context var."""
        with (
            patch(
                "ee.onyx.background.celery.tasks.license.tasks.get_current_tenant_id"
            ) as mock_get_tenant,
            patch(
                "ee.onyx.background.celery.tasks.license.tasks.generate_data_plane_token"
            ) as mock_token,
            patch(
                "ee.onyx.background.celery.tasks.license.tasks._refresh_from_database"
            ) as mock_refresh_db,
        ):
            mock_get_tenant.return_value = "context_tenant"
            mock_token.side_effect = ValueError("DATA_PLANE_SECRET not set")

            result = license_refresh_task(tenant_id="passed_tenant")

            assert result is False
            # Should use passed tenant_id, not context tenant
            mock_refresh_db.assert_called_once_with("passed_tenant")
            mock_get_tenant.assert_not_called()


class TestRefreshFromDatabase:
    """Tests for _refresh_from_database helper function."""

    def test_successful_refresh(self) -> None:
        """Test successful refresh from database."""
        mock_metadata = MagicMock()
        mock_metadata.seats = 50
        mock_metadata.status.value = "active"

        with (
            patch(
                "ee.onyx.background.celery.tasks.license.tasks.get_session_with_current_tenant"
            ) as mock_session,
            patch(
                "ee.onyx.background.celery.tasks.license.tasks.refresh_license_cache"
            ) as mock_refresh,
        ):
            mock_session.return_value.__enter__ = MagicMock()
            mock_session.return_value.__exit__ = MagicMock()
            mock_refresh.return_value = mock_metadata

            # Should not raise
            _refresh_from_database("tenant_123")

            mock_refresh.assert_called_once()

    def test_no_license_in_database(self) -> None:
        """Test refresh when no license exists in database."""
        with (
            patch(
                "ee.onyx.background.celery.tasks.license.tasks.get_session_with_current_tenant"
            ) as mock_session,
            patch(
                "ee.onyx.background.celery.tasks.license.tasks.refresh_license_cache"
            ) as mock_refresh,
        ):
            mock_session.return_value.__enter__ = MagicMock()
            mock_session.return_value.__exit__ = MagicMock()
            mock_refresh.return_value = None

            # Should not raise
            _refresh_from_database("tenant_123")

            mock_refresh.assert_called_once()

    def test_database_error_handled(self) -> None:
        """Test that database errors are handled gracefully."""
        with patch(
            "ee.onyx.background.celery.tasks.license.tasks.get_session_with_current_tenant"
        ) as mock_session:
            mock_session.side_effect = Exception("Database connection failed")

            # Should not raise, just log warning
            _refresh_from_database("tenant_123")
