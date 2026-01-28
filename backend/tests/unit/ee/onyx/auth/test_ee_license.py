"""Tests for the require_ee_license FastAPI dependency."""

from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from onyx.server.settings.models import ApplicationStatus


class TestRequireEeLicense:
    """Tests for the require_ee_license dependency function."""

    @patch(
        "ee.onyx.auth.ee_license.LICENSE_ENFORCEMENT_ENABLED",
        False,
    )
    def test_enforcement_disabled_allows_all(self) -> None:
        """When LICENSE_ENFORCEMENT_ENABLED is False, all requests are allowed."""
        from ee.onyx.auth.ee_license import require_ee_license

        # Should not raise any exception
        result = require_ee_license()
        assert result is None

    @patch(
        "ee.onyx.auth.ee_license.LICENSE_ENFORCEMENT_ENABLED",
        True,
    )
    @patch("ee.onyx.auth.ee_license.MULTI_TENANT", True)
    def test_multi_tenant_skips_check(self) -> None:
        """In multi-tenant mode, the check is skipped (handled by control plane)."""
        from ee.onyx.auth.ee_license import require_ee_license

        # Should not raise any exception
        result = require_ee_license()
        assert result is None

    @patch(
        "ee.onyx.auth.ee_license.LICENSE_ENFORCEMENT_ENABLED",
        True,
    )
    @patch("ee.onyx.auth.ee_license.MULTI_TENANT", False)
    @patch("ee.onyx.auth.ee_license.get_current_tenant_id")
    @patch("ee.onyx.auth.ee_license.get_cached_license_metadata")
    def test_no_license_returns_402(
        self,
        mock_get_metadata: MagicMock,
        mock_get_tenant: MagicMock,
    ) -> None:
        """When no license exists, returns 402 with enterprise_license_required error."""
        from ee.onyx.auth.ee_license import require_ee_license

        mock_get_tenant.return_value = "default"
        mock_get_metadata.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            require_ee_license()

        assert exc_info.value.status_code == 402
        assert exc_info.value.detail["error"] == "enterprise_license_required"

    @patch(
        "ee.onyx.auth.ee_license.LICENSE_ENFORCEMENT_ENABLED",
        True,
    )
    @patch("ee.onyx.auth.ee_license.MULTI_TENANT", False)
    @patch("ee.onyx.auth.ee_license.get_current_tenant_id")
    @patch("ee.onyx.auth.ee_license.get_cached_license_metadata")
    def test_gated_access_returns_402(
        self,
        mock_get_metadata: MagicMock,
        mock_get_tenant: MagicMock,
    ) -> None:
        """When license is in GATED_ACCESS status, returns 402 with license_expired error."""
        from ee.onyx.auth.ee_license import require_ee_license

        mock_get_tenant.return_value = "default"
        mock_metadata = MagicMock()
        mock_metadata.status = ApplicationStatus.GATED_ACCESS
        mock_get_metadata.return_value = mock_metadata

        with pytest.raises(HTTPException) as exc_info:
            require_ee_license()

        assert exc_info.value.status_code == 402
        assert exc_info.value.detail["error"] == "license_expired"

    @patch(
        "ee.onyx.auth.ee_license.LICENSE_ENFORCEMENT_ENABLED",
        True,
    )
    @patch("ee.onyx.auth.ee_license.MULTI_TENANT", False)
    @patch("ee.onyx.auth.ee_license.get_current_tenant_id")
    @patch("ee.onyx.auth.ee_license.get_cached_license_metadata")
    def test_valid_license_allows_access(
        self,
        mock_get_metadata: MagicMock,
        mock_get_tenant: MagicMock,
    ) -> None:
        """When license is valid (ACTIVE status), access is allowed."""
        from ee.onyx.auth.ee_license import require_ee_license

        mock_get_tenant.return_value = "default"
        mock_metadata = MagicMock()
        mock_metadata.status = ApplicationStatus.ACTIVE
        mock_get_metadata.return_value = mock_metadata

        # Should not raise any exception
        result = require_ee_license()
        assert result is None

    @patch(
        "ee.onyx.auth.ee_license.LICENSE_ENFORCEMENT_ENABLED",
        True,
    )
    @patch("ee.onyx.auth.ee_license.MULTI_TENANT", False)
    @patch("ee.onyx.auth.ee_license.get_current_tenant_id")
    @patch("ee.onyx.auth.ee_license.get_cached_license_metadata")
    def test_grace_period_allows_access(
        self,
        mock_get_metadata: MagicMock,
        mock_get_tenant: MagicMock,
    ) -> None:
        """When license is in GRACE_PERIOD status, access is allowed (not blocking)."""
        from ee.onyx.auth.ee_license import require_ee_license

        mock_get_tenant.return_value = "default"
        mock_metadata = MagicMock()
        mock_metadata.status = ApplicationStatus.GRACE_PERIOD
        mock_get_metadata.return_value = mock_metadata

        # Should not raise any exception
        result = require_ee_license()
        assert result is None

    @patch(
        "ee.onyx.auth.ee_license.LICENSE_ENFORCEMENT_ENABLED",
        True,
    )
    @patch("ee.onyx.auth.ee_license.MULTI_TENANT", False)
    @patch("ee.onyx.auth.ee_license.get_current_tenant_id")
    @patch("ee.onyx.auth.ee_license.get_cached_license_metadata")
    def test_cache_error_fails_closed(
        self,
        mock_get_metadata: MagicMock,
        mock_get_tenant: MagicMock,
    ) -> None:
        """When an unexpected error occurs, fail closed with 402."""
        from ee.onyx.auth.ee_license import require_ee_license

        mock_get_tenant.return_value = "default"
        mock_get_metadata.side_effect = RuntimeError("Unexpected error")

        with pytest.raises(HTTPException) as exc_info:
            require_ee_license()

        assert exc_info.value.status_code == 402
        assert exc_info.value.detail["error"] == "license_check_failed"
