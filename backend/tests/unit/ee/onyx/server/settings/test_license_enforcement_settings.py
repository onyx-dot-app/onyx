"""Tests for license enforcement in settings API."""

from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from redis.exceptions import RedisError

from onyx.server.settings.models import ApplicationStatus
from onyx.server.settings.models import Settings


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
        """When LICENSE_ENFORCEMENT_ENABLED=False, EE features are enabled.

        If we're running the EE apply function, EE code was loaded via
        ENABLE_PAID_ENTERPRISE_EDITION_FEATURES, so features should be on.
        """
        from ee.onyx.server.settings.api import apply_license_status_to_settings

        assert base_settings.ee_features_enabled is False
        result = apply_license_status_to_settings(base_settings)
        assert result.application_status == ApplicationStatus.ACTIVE
        assert result.ee_features_enabled is True

    @patch("ee.onyx.server.settings.api.LICENSE_ENFORCEMENT_ENABLED", True)
    @patch("ee.onyx.server.settings.api.MULTI_TENANT", True)
    def test_multi_tenant_enables_ee_features(self, base_settings: Settings) -> None:
        """Cloud mode always enables EE features."""
        from ee.onyx.server.settings.api import apply_license_status_to_settings

        result = apply_license_status_to_settings(base_settings)
        assert result.ee_features_enabled is True

    @pytest.mark.parametrize(
        "license_status,expected_app_status,expected_ee_enabled",
        [
            (ApplicationStatus.GATED_ACCESS, ApplicationStatus.GATED_ACCESS, False),
            (ApplicationStatus.ACTIVE, ApplicationStatus.ACTIVE, True),
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
        license_status: ApplicationStatus | None,
        expected_app_status: ApplicationStatus,
        expected_ee_enabled: bool,
        base_settings: Settings,
    ) -> None:
        """Self-hosted: license status controls both application_status and ee_features_enabled."""
        from ee.onyx.server.settings.api import apply_license_status_to_settings

        mock_get_tenant.return_value = "test_tenant"
        if license_status is None:
            mock_get_metadata.return_value = None
        else:
            mock_metadata = MagicMock()
            mock_metadata.status = license_status
            mock_get_metadata.return_value = mock_metadata

        result = apply_license_status_to_settings(base_settings)
        assert result.application_status == expected_app_status
        assert result.ee_features_enabled is expected_ee_enabled

    @patch("ee.onyx.server.settings.api.ENTERPRISE_EDITION_ENABLED", True)
    @patch("ee.onyx.server.settings.api.LICENSE_ENFORCEMENT_ENABLED", True)
    @patch("ee.onyx.server.settings.api.MULTI_TENANT", False)
    @patch("ee.onyx.server.settings.api.get_current_tenant_id")
    @patch("ee.onyx.server.settings.api.get_cached_license_metadata")
    def test_no_license_with_ee_flag_gates_access(
        self,
        mock_get_metadata: MagicMock,
        mock_get_tenant: MagicMock,
        base_settings: Settings,
    ) -> None:
        """No license + ENTERPRISE_EDITION_ENABLED=true → GATED_ACCESS."""
        from ee.onyx.server.settings.api import apply_license_status_to_settings

        mock_get_tenant.return_value = "test_tenant"
        mock_get_metadata.return_value = None

        result = apply_license_status_to_settings(base_settings)
        assert result.application_status == ApplicationStatus.GATED_ACCESS
        assert result.ee_features_enabled is False

    @patch("ee.onyx.server.settings.api.ENTERPRISE_EDITION_ENABLED", False)
    @patch("ee.onyx.server.settings.api.LICENSE_ENFORCEMENT_ENABLED", True)
    @patch("ee.onyx.server.settings.api.MULTI_TENANT", False)
    @patch("ee.onyx.server.settings.api.get_current_tenant_id")
    @patch("ee.onyx.server.settings.api.get_cached_license_metadata")
    def test_no_license_without_ee_flag_allows_community(
        self,
        mock_get_metadata: MagicMock,
        mock_get_tenant: MagicMock,
        base_settings: Settings,
    ) -> None:
        """No license + ENTERPRISE_EDITION_ENABLED=false → community mode (no gating)."""
        from ee.onyx.server.settings.api import apply_license_status_to_settings

        mock_get_tenant.return_value = "test_tenant"
        mock_get_metadata.return_value = None

        result = apply_license_status_to_settings(base_settings)
        assert result.application_status == ApplicationStatus.ACTIVE
        assert result.ee_features_enabled is False

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
        assert result.application_status == ApplicationStatus.ACTIVE
        assert result.ee_features_enabled is False


class TestSettingsDefaultEEDisabled:
    """Verify the Settings model defaults ee_features_enabled to False."""

    def test_default_ee_features_disabled(self) -> None:
        settings = Settings()
        assert settings.ee_features_enabled is False
