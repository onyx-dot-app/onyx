"""Tests for proxy endpoints for self-hosted data planes."""

from datetime import datetime
from datetime import timedelta
from datetime import timezone
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from ee.onyx.server.license.models import LicensePayload
from ee.onyx.server.license.models import PlanType
from ee.onyx.server.tenants.proxy import forward_to_control_plane
from ee.onyx.server.tenants.proxy import get_license_payload
from ee.onyx.server.tenants.proxy import get_license_payload_allow_expired
from ee.onyx.server.tenants.proxy import get_optional_license_payload
from ee.onyx.server.tenants.proxy import verify_license_auth


def make_license_payload(
    tenant_id: str = "tenant_123",
    expired: bool = False,
) -> LicensePayload:
    """Helper to create a test LicensePayload."""
    now = datetime.now(timezone.utc)
    if expired:
        expires_at = now - timedelta(days=1)
    else:
        expires_at = now + timedelta(days=30)

    return LicensePayload(
        version="1.0",
        tenant_id=tenant_id,
        organization_name="Test Org",
        issued_at=now - timedelta(days=1),
        expires_at=expires_at,
        seats=10,
        plan_type=PlanType.MONTHLY,
    )


class TestVerifyLicenseAuth:
    """Tests for verify_license_auth function."""

    def test_valid_license(self) -> None:
        """Test that a valid license passes verification."""
        payload = make_license_payload()

        with patch(
            "ee.onyx.server.tenants.proxy.verify_license_signature"
        ) as mock_verify:
            mock_verify.return_value = payload

            result = verify_license_auth("valid_license_data", allow_expired=False)

            assert result == payload
            mock_verify.assert_called_once_with("valid_license_data")

    def test_invalid_signature(self) -> None:
        """Test that invalid signature raises 401."""
        with patch(
            "ee.onyx.server.tenants.proxy.verify_license_signature"
        ) as mock_verify:
            mock_verify.side_effect = ValueError("Invalid signature")

            with pytest.raises(HTTPException) as exc_info:
                verify_license_auth("bad_license", allow_expired=False)

            assert exc_info.value.status_code == 401
            assert "Invalid license" in str(exc_info.value.detail)

    def test_expired_license_rejected(self) -> None:
        """Test that expired license raises 401 when not allowed."""
        payload = make_license_payload(expired=True)

        with (
            patch(
                "ee.onyx.server.tenants.proxy.verify_license_signature"
            ) as mock_verify,
            patch("ee.onyx.server.tenants.proxy.is_license_valid") as mock_valid,
        ):
            mock_verify.return_value = payload
            mock_valid.return_value = False

            with pytest.raises(HTTPException) as exc_info:
                verify_license_auth("expired_license", allow_expired=False)

            assert exc_info.value.status_code == 401
            assert "expired" in str(exc_info.value.detail).lower()

    def test_expired_license_allowed(self) -> None:
        """Test that expired license is allowed when allow_expired=True."""
        payload = make_license_payload(expired=True)

        with (
            patch(
                "ee.onyx.server.tenants.proxy.verify_license_signature"
            ) as mock_verify,
            patch("ee.onyx.server.tenants.proxy.is_license_valid") as mock_valid,
        ):
            mock_verify.return_value = payload
            mock_valid.return_value = False

            result = verify_license_auth("expired_license", allow_expired=True)

            assert result == payload


class TestGetLicensePayload:
    """Tests for get_license_payload dependency."""

    @pytest.mark.asyncio
    async def test_valid_license(self) -> None:
        """Test that valid license returns payload."""
        payload = make_license_payload()

        with (
            patch(
                "ee.onyx.server.tenants.proxy.verify_license_signature"
            ) as mock_verify,
            patch("ee.onyx.server.tenants.proxy.is_license_valid") as mock_valid,
        ):
            mock_verify.return_value = payload
            mock_valid.return_value = True

            result = await get_license_payload("Bearer valid_license_data")

            assert result == payload

    @pytest.mark.asyncio
    async def test_missing_auth_header(self) -> None:
        """Test that missing Authorization header raises 401."""
        with pytest.raises(HTTPException) as exc_info:
            await get_license_payload(None)

        assert exc_info.value.status_code == 401
        assert "Missing or invalid authorization header" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_invalid_auth_format(self) -> None:
        """Test that non-Bearer auth raises 401."""
        with pytest.raises(HTTPException) as exc_info:
            await get_license_payload("Basic sometoken")

        assert exc_info.value.status_code == 401


class TestGetLicensePayloadAllowExpired:
    """Tests for get_license_payload_allow_expired dependency."""

    @pytest.mark.asyncio
    async def test_expired_license_allowed(self) -> None:
        """Test that expired license is accepted."""
        payload = make_license_payload(expired=True)

        with (
            patch(
                "ee.onyx.server.tenants.proxy.verify_license_signature"
            ) as mock_verify,
        ):
            mock_verify.return_value = payload

            result = await get_license_payload_allow_expired("Bearer expired_license")

            assert result == payload

    @pytest.mark.asyncio
    async def test_missing_auth_header(self) -> None:
        """Test that missing Authorization header raises 401."""
        with pytest.raises(HTTPException) as exc_info:
            await get_license_payload_allow_expired(None)

        assert exc_info.value.status_code == 401


class TestGetOptionalLicensePayload:
    """Tests for get_optional_license_payload dependency."""

    @pytest.mark.asyncio
    async def test_no_auth_returns_none(self) -> None:
        """Test that missing auth returns None (for new customers)."""
        result = await get_optional_license_payload(None)
        assert result is None

    @pytest.mark.asyncio
    async def test_non_bearer_returns_none(self) -> None:
        """Test that non-Bearer auth returns None."""
        result = await get_optional_license_payload("Basic sometoken")
        assert result is None

    @pytest.mark.asyncio
    async def test_valid_license_returns_payload(self) -> None:
        """Test that valid license returns payload."""
        payload = make_license_payload()

        with (
            patch(
                "ee.onyx.server.tenants.proxy.verify_license_signature"
            ) as mock_verify,
        ):
            mock_verify.return_value = payload

            result = await get_optional_license_payload("Bearer valid_license")

            assert result == payload


class TestForwardToControlPlane:
    """Tests for forward_to_control_plane function."""

    def test_successful_get_request(self) -> None:
        """Test successful GET request forwarding."""
        with (
            patch(
                "ee.onyx.server.tenants.proxy.generate_data_plane_token"
            ) as mock_token,
            patch("ee.onyx.server.tenants.proxy.requests.get") as mock_get,
            patch(
                "ee.onyx.server.tenants.proxy.CONTROL_PLANE_API_BASE_URL",
                "https://control.example.com",
            ),
        ):
            mock_token.return_value = "cp_token"
            mock_response = MagicMock()
            mock_response.json.return_value = {"data": "test"}
            mock_get.return_value = mock_response

            result = forward_to_control_plane(
                "GET", "/test-endpoint", params={"key": "value"}
            )

            assert result == {"data": "test"}
            mock_get.assert_called_once()
            call_args = mock_get.call_args
            assert call_args[0][0] == "https://control.example.com/test-endpoint"
            assert call_args[1]["params"] == {"key": "value"}

    def test_successful_post_request(self) -> None:
        """Test successful POST request forwarding."""
        with (
            patch(
                "ee.onyx.server.tenants.proxy.generate_data_plane_token"
            ) as mock_token,
            patch("ee.onyx.server.tenants.proxy.requests.post") as mock_post,
            patch(
                "ee.onyx.server.tenants.proxy.CONTROL_PLANE_API_BASE_URL",
                "https://control.example.com",
            ),
        ):
            mock_token.return_value = "cp_token"
            mock_response = MagicMock()
            mock_response.json.return_value = {"url": "https://checkout.stripe.com"}
            mock_post.return_value = mock_response

            result = forward_to_control_plane(
                "POST", "/create-checkout-session", body={"tenant_id": "t1"}
            )

            assert result == {"url": "https://checkout.stripe.com"}
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            assert call_args[1]["json"] == {"tenant_id": "t1"}

    def test_http_error_with_detail(self) -> None:
        """Test HTTP error handling with detail from response."""
        with (
            patch(
                "ee.onyx.server.tenants.proxy.generate_data_plane_token"
            ) as mock_token,
            patch("ee.onyx.server.tenants.proxy.requests.get") as mock_get,
            patch(
                "ee.onyx.server.tenants.proxy.CONTROL_PLANE_API_BASE_URL",
                "https://control.example.com",
            ),
        ):
            mock_token.return_value = "cp_token"
            mock_response = MagicMock()
            mock_response.status_code = 404
            mock_response.json.return_value = {"detail": "Tenant not found"}

            import requests

            mock_get.return_value.raise_for_status.side_effect = requests.HTTPError(
                response=mock_response
            )
            mock_get.return_value = mock_response
            mock_response.raise_for_status.side_effect = requests.HTTPError(
                response=mock_response
            )

            with pytest.raises(HTTPException) as exc_info:
                forward_to_control_plane("GET", "/billing-information")

            assert exc_info.value.status_code == 404
            assert "Tenant not found" in str(exc_info.value.detail)

    def test_connection_error(self) -> None:
        """Test connection error handling."""
        with (
            patch(
                "ee.onyx.server.tenants.proxy.generate_data_plane_token"
            ) as mock_token,
            patch("ee.onyx.server.tenants.proxy.requests.get") as mock_get,
            patch(
                "ee.onyx.server.tenants.proxy.CONTROL_PLANE_API_BASE_URL",
                "https://control.example.com",
            ),
        ):
            mock_token.return_value = "cp_token"

            import requests

            mock_get.side_effect = requests.RequestException("Connection refused")

            with pytest.raises(HTTPException) as exc_info:
                forward_to_control_plane("GET", "/test")

            assert exc_info.value.status_code == 502
            assert "Failed to connect to control plane" in str(exc_info.value.detail)

    def test_unsupported_method(self) -> None:
        """Test that unsupported HTTP methods raise ValueError."""
        with (
            patch(
                "ee.onyx.server.tenants.proxy.generate_data_plane_token"
            ) as mock_token,
            patch(
                "ee.onyx.server.tenants.proxy.CONTROL_PLANE_API_BASE_URL",
                "https://control.example.com",
            ),
        ):
            mock_token.return_value = "cp_token"

            with pytest.raises(ValueError, match="Unsupported HTTP method"):
                forward_to_control_plane("DELETE", "/test")
