"""Tests for the billing proxy endpoints."""

from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import httpx
import pytest

from .conftest import make_license_payload
from .conftest import make_mock_http_client
from .conftest import make_mock_response
from ee.onyx.server.license.models import LicensePayload


class TestProxySeatUpdate:
    """Tests for proxy_seat_update endpoint."""

    @pytest.mark.asyncio
    @patch("ee.onyx.server.tenants.proxy.forward_to_control_plane")
    async def test_proxies_seat_update(
        self,
        mock_forward: AsyncMock,
    ) -> None:
        """Should forward seat update request to control plane."""
        from ee.onyx.server.billing.models import SeatUpdateRequest
        from ee.onyx.server.tenants.proxy import proxy_seat_update

        mock_forward.return_value = {
            "success": True,
            "current_seats": 15,
            "used_seats": 5,
            "message": "Seats updated",
        }

        license_payload = make_license_payload(tenant_id="tenant_123", seats=10)

        request = SeatUpdateRequest(new_seat_count=15)
        result = await proxy_seat_update(
            request_body=request,
            license_payload=license_payload,
        )

        assert result.success is True
        assert result.current_seats == 15
        assert result.used_seats == 5

        mock_forward.assert_called_once_with(
            "POST",
            "/seats/update",
            body={
                "tenant_id": "tenant_123",
                "new_seat_count": 15,
            },
        )

    @pytest.mark.asyncio
    async def test_rejects_missing_tenant_id(self) -> None:
        """Should reject license without tenant_id."""
        from fastapi import HTTPException

        from ee.onyx.server.billing.models import SeatUpdateRequest
        from ee.onyx.server.tenants.proxy import proxy_seat_update

        # Create a license payload without tenant_id by using a mock
        license_payload = MagicMock(spec=LicensePayload)
        license_payload.tenant_id = None

        request = SeatUpdateRequest(new_seat_count=10)

        with pytest.raises(HTTPException) as exc_info:
            await proxy_seat_update(
                request_body=request,
                license_payload=license_payload,
            )

        assert exc_info.value.status_code == 401
        assert "tenant_id" in exc_info.value.detail


class TestForwardToControlPlane:
    """Tests for forward_to_control_plane helper."""

    @pytest.mark.asyncio
    @patch("ee.onyx.server.tenants.proxy.generate_data_plane_token")
    @patch("ee.onyx.server.tenants.proxy.CONTROL_PLANE_API_BASE_URL", "https://cp.test")
    async def test_forwards_post_request(
        self,
        mock_token: MagicMock,
    ) -> None:
        """Should forward POST request with JWT auth."""
        from ee.onyx.server.tenants.proxy import forward_to_control_plane

        mock_token.return_value = "jwt_token"
        mock_response = make_mock_response({"result": "success"})
        mock_client = make_mock_http_client("post", response=mock_response)

        with patch("httpx.AsyncClient", mock_client):
            result = await forward_to_control_plane(
                "POST",
                "/test-path",
                body={"key": "value"},
            )

        assert result == {"result": "success"}

    @pytest.mark.asyncio
    @patch("ee.onyx.server.tenants.proxy.generate_data_plane_token")
    @patch("ee.onyx.server.tenants.proxy.CONTROL_PLANE_API_BASE_URL", "https://cp.test")
    async def test_forwards_get_request(
        self,
        mock_token: MagicMock,
    ) -> None:
        """Should forward GET request with params."""
        from ee.onyx.server.tenants.proxy import forward_to_control_plane

        mock_token.return_value = "jwt_token"
        mock_response = make_mock_response({"data": "test"})
        mock_client = make_mock_http_client("get", response=mock_response)

        with patch("httpx.AsyncClient", mock_client):
            result = await forward_to_control_plane(
                "GET",
                "/billing-info",
                params={"tenant_id": "123"},
            )

        assert result == {"data": "test"}

    @pytest.mark.asyncio
    @patch("ee.onyx.server.tenants.proxy.generate_data_plane_token")
    @patch("ee.onyx.server.tenants.proxy.CONTROL_PLANE_API_BASE_URL", "https://cp.test")
    async def test_raises_on_http_error(
        self,
        mock_token: MagicMock,
    ) -> None:
        """Should raise HTTPException on HTTP error."""
        from fastapi import HTTPException

        from ee.onyx.server.tenants.proxy import forward_to_control_plane

        mock_token.return_value = "jwt_token"
        mock_response = make_mock_response({"detail": "Bad request"})
        mock_response.status_code = 400
        error = httpx.HTTPStatusError(
            "Error", request=MagicMock(), response=mock_response
        )
        mock_client = make_mock_http_client("post", side_effect=error)

        with patch("httpx.AsyncClient", mock_client):
            with pytest.raises(HTTPException) as exc_info:
                await forward_to_control_plane("POST", "/test")

        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    @patch("ee.onyx.server.tenants.proxy.generate_data_plane_token")
    @patch("ee.onyx.server.tenants.proxy.CONTROL_PLANE_API_BASE_URL", "https://cp.test")
    async def test_raises_on_connection_error(
        self,
        mock_token: MagicMock,
    ) -> None:
        """Should raise HTTPException on connection error."""
        from fastapi import HTTPException

        from ee.onyx.server.tenants.proxy import forward_to_control_plane

        mock_token.return_value = "jwt_token"
        error = httpx.RequestError("Connection failed")
        mock_client = make_mock_http_client("post", side_effect=error)

        with patch("httpx.AsyncClient", mock_client):
            with pytest.raises(HTTPException) as exc_info:
                await forward_to_control_plane("POST", "/test")

        assert exc_info.value.status_code == 502
        assert "Failed to connect" in exc_info.value.detail


class TestVerifyLicenseAuth:
    """Tests for verify_license_auth helper."""

    @pytest.mark.asyncio
    @patch("ee.onyx.server.tenants.proxy.LICENSE_ENFORCEMENT_ENABLED", True)
    @patch("ee.onyx.server.tenants.proxy.verify_license_signature")
    @patch("ee.onyx.server.tenants.proxy.is_license_valid")
    async def test_valid_license(
        self,
        mock_is_valid: MagicMock,
        mock_verify: MagicMock,
    ) -> None:
        """Should return payload for valid license."""
        from ee.onyx.server.tenants.proxy import verify_license_auth

        mock_payload = make_license_payload()
        mock_verify.return_value = mock_payload
        mock_is_valid.return_value = True

        result = verify_license_auth("valid_license_blob")

        assert result == mock_payload

    @pytest.mark.asyncio
    @patch("ee.onyx.server.tenants.proxy.LICENSE_ENFORCEMENT_ENABLED", True)
    @patch("ee.onyx.server.tenants.proxy.verify_license_signature")
    async def test_invalid_signature(
        self,
        mock_verify: MagicMock,
    ) -> None:
        """Should reject invalid license signature."""
        from fastapi import HTTPException

        from ee.onyx.server.tenants.proxy import verify_license_auth

        mock_verify.side_effect = ValueError("Invalid signature")

        with pytest.raises(HTTPException) as exc_info:
            verify_license_auth("invalid_license")

        assert exc_info.value.status_code == 401
        assert "Invalid license" in exc_info.value.detail

    @pytest.mark.asyncio
    @patch("ee.onyx.server.tenants.proxy.LICENSE_ENFORCEMENT_ENABLED", True)
    @patch("ee.onyx.server.tenants.proxy.verify_license_signature")
    @patch("ee.onyx.server.tenants.proxy.is_license_valid")
    async def test_expired_license_rejected(
        self,
        mock_is_valid: MagicMock,
        mock_verify: MagicMock,
    ) -> None:
        """Should reject expired license when allow_expired=False."""
        from fastapi import HTTPException

        from ee.onyx.server.tenants.proxy import verify_license_auth

        mock_payload = make_license_payload(expired=True)
        mock_verify.return_value = mock_payload
        mock_is_valid.return_value = False

        with pytest.raises(HTTPException) as exc_info:
            verify_license_auth("expired_license", allow_expired=False)

        assert exc_info.value.status_code == 401
        assert "expired" in exc_info.value.detail

    @pytest.mark.asyncio
    @patch("ee.onyx.server.tenants.proxy.LICENSE_ENFORCEMENT_ENABLED", True)
    @patch("ee.onyx.server.tenants.proxy.verify_license_signature")
    @patch("ee.onyx.server.tenants.proxy.is_license_valid")
    async def test_expired_license_allowed(
        self,
        mock_is_valid: MagicMock,
        mock_verify: MagicMock,
    ) -> None:
        """Should accept expired license when allow_expired=True."""
        from ee.onyx.server.tenants.proxy import verify_license_auth

        mock_payload = make_license_payload(expired=True)
        mock_verify.return_value = mock_payload
        mock_is_valid.return_value = False

        result = verify_license_auth("expired_license", allow_expired=True)

        assert result == mock_payload
