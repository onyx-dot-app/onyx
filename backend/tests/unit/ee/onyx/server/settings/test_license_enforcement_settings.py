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
    def test_enforcement_disabled_returns_unchanged(
        self, base_settings: Settings
    ) -> None:
        """Critical: When LICENSE_ENFORCEMENT_ENABLED=False, settings remain unchanged.

        This is the key behavior that allows disabling enforcement for rollback.
        """
        from ee.onyx.server.settings.api import apply_license_status_to_settings

        result = apply_license_status_to_settings(base_settings)
        assert result.application_status == ApplicationStatus.ACTIVE

    @pytest.mark.parametrize(
        "license_status,expected_status",
        [
            (None, ApplicationStatus.GATED_ACCESS),  # No license = gated
            (
                ApplicationStatus.GATED_ACCESS,
                ApplicationStatus.GATED_ACCESS,
            ),  # Gated status propagated
            (ApplicationStatus.ACTIVE, ApplicationStatus.ACTIVE),  # Active stays active
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
        expected_status: ApplicationStatus,
        base_settings: Settings,
    ) -> None:
        """Self-hosted: license status is propagated to settings correctly."""
        from ee.onyx.server.settings.api import apply_license_status_to_settings

        mock_get_tenant.return_value = "test_tenant"
        if license_status is None:
            mock_get_metadata.return_value = None
        else:
            mock_metadata = MagicMock()
            mock_metadata.status = license_status
            mock_get_metadata.return_value = mock_metadata

        result = apply_license_status_to_settings(base_settings)
        assert result.application_status == expected_status

    @patch("ee.onyx.server.settings.api.LICENSE_ENFORCEMENT_ENABLED", True)
    @patch("ee.onyx.server.settings.api.MULTI_TENANT", False)
    @patch("ee.onyx.server.settings.api.get_current_tenant_id")
    @patch("ee.onyx.server.settings.api.get_cached_license_metadata")
    def test_redis_error_fails_open(
        self,
        mock_get_metadata: MagicMock,
        mock_get_tenant: MagicMock,
        base_settings: Settings,
    ) -> None:
        """Redis errors should not block users - fail open."""
        from ee.onyx.server.settings.api import apply_license_status_to_settings

        mock_get_tenant.return_value = "test_tenant"
        mock_get_metadata.side_effect = RedisError("Connection failed")

        result = apply_license_status_to_settings(base_settings)
        assert result.application_status == ApplicationStatus.ACTIVE
