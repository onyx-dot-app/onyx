"""Tests for license enforcement in settings API."""

from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from redis.exceptions import RedisError

from onyx.server.settings.models import ApplicationStatus
from onyx.server.settings.models import Settings

# Fields we assert on across all tests
_ASSERT_FIELDS = {
    "application_status",
    "ee_features_enabled",
    "seat_count",
    "used_seats",
}


def _pick(settings: Settings) -> dict:
    """Extract only the fields under test from a Settings object."""
    return settings.model_dump(include=_ASSERT_FIELDS)


@pytest.fixture
def base_settings() -> Settings:
    """Create base settings for testing."""
    return Settings(
        maximum_chat_retention_days=None,
        gpu_enabled=False,
        application_status=ApplicationStatus.ACTIVE,
    )


class TestApplyLicenseStatusToSettings:
    """Tests for apply_license_status_to_settings function."""

    @patch("ee.onyx.server.settings.api.LICENSE_ENFORCEMENT_ENABLED", False)
    def test_enforcement_disabled_enables_ee_features(
        self, base_settings: Settings
    ) -> None:
        """When LICENSE_ENFORCEMENT_ENABLED=False, EE features are enabled."""
        from ee.onyx.server.settings.api import apply_license_status_to_settings

        assert base_settings.ee_features_enabled is False
        result = apply_license_status_to_settings(base_settings)
        assert _pick(result) == {
            "application_status": ApplicationStatus.ACTIVE,
            "ee_features_enabled": True,
            "seat_count": None,
            "used_seats": None,
        }

    @patch("ee.onyx.server.settings.api.LICENSE_ENFORCEMENT_ENABLED", True)
    @patch("ee.onyx.server.settings.api.MULTI_TENANT", True)
    def test_multi_tenant_enables_ee_features(self, base_settings: Settings) -> None:
        """Cloud mode always enables EE features."""
        from ee.onyx.server.settings.api import apply_license_status_to_settings

        result = apply_license_status_to_settings(base_settings)
        assert _pick(result) == {
            "application_status": ApplicationStatus.ACTIVE,
            "ee_features_enabled": True,
            "seat_count": None,
            "used_seats": None,
        }

    @pytest.mark.parametrize(
        "license_status,used_seats,seats,expected",
        [
            (
                ApplicationStatus.GATED_ACCESS,
                3,
                10,
                {
                    "application_status": ApplicationStatus.GATED_ACCESS,
                    "ee_features_enabled": False,
                    "seat_count": None,
                    "used_seats": None,
                },
            ),
            (
                ApplicationStatus.ACTIVE,
                3,
                10,
                {
                    "application_status": ApplicationStatus.ACTIVE,
                    "ee_features_enabled": True,
                    "seat_count": None,
                    "used_seats": None,
                },
            ),
            (
                ApplicationStatus.ACTIVE,
                10,
                10,
                {
                    "application_status": ApplicationStatus.ACTIVE,
                    "ee_features_enabled": True,
                    "seat_count": None,
                    "used_seats": None,
                },
            ),
            (
                ApplicationStatus.GRACE_PERIOD,
                3,
                10,
                {
                    "application_status": ApplicationStatus.ACTIVE,
                    "ee_features_enabled": True,
                    "seat_count": None,
                    "used_seats": None,
                },
            ),
        ],
    )
    @patch("ee.onyx.server.settings.api.LICENSE_ENFORCEMENT_ENABLED", True)
    @patch("ee.onyx.server.settings.api.MULTI_TENANT", False)
    @patch("ee.onyx.server.settings.api.get_current_tenant_id")
    @patch("ee.onyx.server.settings.api.get_cached_license_metadata")
    def test_self_hosted_license_status_propagation(
        self,
        mock_get_metadata: MagicMock,
        mock_get_tenant: MagicMock,
        license_status: ApplicationStatus,
        used_seats: int,
        seats: int,
        expected: dict,
        base_settings: Settings,
    ) -> None:
        """Self-hosted: license status controls both application_status and ee_features_enabled."""
        from ee.onyx.server.settings.api import apply_license_status_to_settings

        mock_get_tenant.return_value = "test_tenant"
        mock_metadata = MagicMock()
        mock_metadata.status = license_status
        mock_metadata.used_seats = used_seats
        mock_metadata.seats = seats
        mock_get_metadata.return_value = mock_metadata

        result = apply_license_status_to_settings(base_settings)
        assert _pick(result) == expected

    @patch("ee.onyx.server.settings.api.LICENSE_ENFORCEMENT_ENABLED", True)
    @patch("ee.onyx.server.settings.api.MULTI_TENANT", False)
    @patch("ee.onyx.server.settings.api.get_current_tenant_id")
    @patch("ee.onyx.server.settings.api.get_cached_license_metadata")
    def test_seat_limit_exceeded_sets_status_and_counts(
        self,
        mock_get_metadata: MagicMock,
        mock_get_tenant: MagicMock,
        base_settings: Settings,
    ) -> None:
        """Seat limit exceeded sets SEAT_LIMIT_EXCEEDED with counts, keeps EE enabled."""
        from ee.onyx.server.settings.api import apply_license_status_to_settings

        mock_get_tenant.return_value = "test_tenant"
        mock_metadata = MagicMock()
        mock_metadata.status = ApplicationStatus.ACTIVE
        mock_metadata.used_seats = 15
        mock_metadata.seats = 10
        mock_get_metadata.return_value = mock_metadata

        result = apply_license_status_to_settings(base_settings)
        assert _pick(result) == {
            "application_status": ApplicationStatus.SEAT_LIMIT_EXCEEDED,
            "ee_features_enabled": True,
            "seat_count": 10,
            "used_seats": 15,
        }

    @patch("ee.onyx.server.settings.api.LICENSE_ENFORCEMENT_ENABLED", True)
    @patch("ee.onyx.server.settings.api.MULTI_TENANT", False)
    @patch("ee.onyx.server.settings.api.get_current_tenant_id")
    @patch("ee.onyx.server.settings.api.get_cached_license_metadata")
    def test_expired_license_takes_precedence_over_seat_limit(
        self,
        mock_get_metadata: MagicMock,
        mock_get_tenant: MagicMock,
        base_settings: Settings,
    ) -> None:
        """Expired license (GATED_ACCESS) takes precedence over seat limit exceeded."""
        from ee.onyx.server.settings.api import apply_license_status_to_settings

        mock_get_tenant.return_value = "test_tenant"
        mock_metadata = MagicMock()
        mock_metadata.status = ApplicationStatus.GATED_ACCESS
        mock_metadata.used_seats = 15
        mock_metadata.seats = 10
        mock_get_metadata.return_value = mock_metadata

        result = apply_license_status_to_settings(base_settings)
        assert _pick(result) == {
            "application_status": ApplicationStatus.GATED_ACCESS,
            "ee_features_enabled": False,
            "seat_count": None,
            "used_seats": None,
        }

    @patch("ee.onyx.server.settings.api.ENTERPRISE_EDITION_ENABLED", True)
    @patch("ee.onyx.server.settings.api.LICENSE_ENFORCEMENT_ENABLED", True)
    @patch("ee.onyx.server.settings.api.MULTI_TENANT", False)
    @patch("ee.onyx.server.settings.api.refresh_license_cache", return_value=None)
    @patch("ee.onyx.server.settings.api.get_session_with_current_tenant")
    @patch("ee.onyx.server.settings.api.get_current_tenant_id")
    @patch("ee.onyx.server.settings.api.get_cached_license_metadata")
    def test_no_license_with_ee_flag_gates_access(
        self,
        mock_get_metadata: MagicMock,
        mock_get_tenant: MagicMock,
        _mock_get_session: MagicMock,
        _mock_refresh: MagicMock,
        base_settings: Settings,
    ) -> None:
        """No license + ENTERPRISE_EDITION_ENABLED=true → GATED_ACCESS."""
        from ee.onyx.server.settings.api import apply_license_status_to_settings

        mock_get_tenant.return_value = "test_tenant"
        mock_get_metadata.return_value = None

        result = apply_license_status_to_settings(base_settings)
        assert _pick(result) == {
            "application_status": ApplicationStatus.GATED_ACCESS,
            "ee_features_enabled": False,
            "seat_count": None,
            "used_seats": None,
        }

    @patch("ee.onyx.server.settings.api.ENTERPRISE_EDITION_ENABLED", False)
    @patch("ee.onyx.server.settings.api.LICENSE_ENFORCEMENT_ENABLED", True)
    @patch("ee.onyx.server.settings.api.MULTI_TENANT", False)
    @patch("ee.onyx.server.settings.api.refresh_license_cache", return_value=None)
    @patch("ee.onyx.server.settings.api.get_session_with_current_tenant")
    @patch("ee.onyx.server.settings.api.get_current_tenant_id")
    @patch("ee.onyx.server.settings.api.get_cached_license_metadata")
    def test_no_license_without_ee_flag_allows_community(
        self,
        mock_get_metadata: MagicMock,
        mock_get_tenant: MagicMock,
        _mock_get_session: MagicMock,
        _mock_refresh: MagicMock,
        base_settings: Settings,
    ) -> None:
        """No license + ENTERPRISE_EDITION_ENABLED=false → community mode (no gating)."""
        from ee.onyx.server.settings.api import apply_license_status_to_settings

        mock_get_tenant.return_value = "test_tenant"
        mock_get_metadata.return_value = None

        result = apply_license_status_to_settings(base_settings)
        assert _pick(result) == {
            "application_status": ApplicationStatus.ACTIVE,
            "ee_features_enabled": False,
            "seat_count": None,
            "used_seats": None,
        }

    @patch("ee.onyx.server.settings.api.LICENSE_ENFORCEMENT_ENABLED", True)
    @patch("ee.onyx.server.settings.api.MULTI_TENANT", False)
    @patch("ee.onyx.server.settings.api.get_current_tenant_id")
    @patch("ee.onyx.server.settings.api.get_cached_license_metadata")
    def test_redis_error_disables_ee_features(
        self,
        mock_get_metadata: MagicMock,
        mock_get_tenant: MagicMock,
        base_settings: Settings,
    ) -> None:
        """Redis errors fail closed - disable EE features."""
        from ee.onyx.server.settings.api import apply_license_status_to_settings

        mock_get_tenant.return_value = "test_tenant"
        mock_get_metadata.side_effect = RedisError("Connection failed")

        result = apply_license_status_to_settings(base_settings)
        assert _pick(result) == {
            "application_status": ApplicationStatus.ACTIVE,
            "ee_features_enabled": False,
            "seat_count": None,
            "used_seats": None,
        }


class TestSettingsDefaultEEDisabled:
    """Verify the Settings model defaults ee_features_enabled to False."""

    def test_default_ee_features_disabled(self) -> None:
        settings = Settings()
        assert settings.ee_features_enabled is False
