"""Tests for proxy endpoints for self-hosted data planes."""

from unittest.mock import MagicMock
from unittest.mock import patch

import jwt
import pytest
from fastapi import HTTPException

from ee.onyx.server.tenants.proxy import forward_to_control_plane
from ee.onyx.server.tenants.proxy import verify_self_hosted_token


class TestVerifySelfHostedToken:
    """Tests for verify_self_hosted_token function."""

    @pytest.mark.asyncio
    async def test_valid_token(self) -> None:
        """Test that a valid token passes verification."""
        mock_request = MagicMock()
        mock_request.headers.get.side_effect = lambda key: {
            "Authorization": "Bearer valid_token",
            "X-Tenant-ID": "tenant_123",
        }.get(key)

        with (
            patch("ee.onyx.server.tenants.proxy.DATA_PLANE_SECRET", "test_secret"),
            patch("ee.onyx.server.tenants.proxy.jwt.decode") as mock_decode,
        ):
            mock_decode.return_value = {"sub": "test"}

            result = await verify_self_hosted_token(mock_request)

            assert result == "tenant_123"
            mock_decode.assert_called_once_with(
                "valid_token", "test_secret", algorithms=["HS256"]
            )

    @pytest.mark.asyncio
    async def test_missing_auth_header(self) -> None:
        """Test that missing Authorization header raises 401."""
        mock_request = MagicMock()
        mock_request.headers.get.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await verify_self_hosted_token(mock_request)

        assert exc_info.value.status_code == 401
        assert "Missing or invalid authorization header" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_invalid_auth_format(self) -> None:
        """Test that non-Bearer auth raises 401."""
        mock_request = MagicMock()
        mock_request.headers.get.side_effect = lambda key: {
            "Authorization": "Basic sometoken",
        }.get(key)

        with pytest.raises(HTTPException) as exc_info:
            await verify_self_hosted_token(mock_request)

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_no_data_plane_secret(self) -> None:
        """Test that missing DATA_PLANE_SECRET raises 500."""
        mock_request = MagicMock()
        mock_request.headers.get.side_effect = lambda key: {
            "Authorization": "Bearer valid_token",
        }.get(key)

        with patch("ee.onyx.server.tenants.proxy.DATA_PLANE_SECRET", None):
            with pytest.raises(HTTPException) as exc_info:
                await verify_self_hosted_token(mock_request)

            assert exc_info.value.status_code == 500
            assert "Proxy not configured" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_expired_token(self) -> None:
        """Test that expired token raises 401."""
        mock_request = MagicMock()
        mock_request.headers.get.side_effect = lambda key: {
            "Authorization": "Bearer expired_token",
            "X-Tenant-ID": "tenant_123",
        }.get(key)

        with (
            patch("ee.onyx.server.tenants.proxy.DATA_PLANE_SECRET", "test_secret"),
            patch("ee.onyx.server.tenants.proxy.jwt.decode") as mock_decode,
        ):
            mock_decode.side_effect = jwt.ExpiredSignatureError()

            with pytest.raises(HTTPException) as exc_info:
                await verify_self_hosted_token(mock_request)

            assert exc_info.value.status_code == 401
            assert "Token has expired" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_invalid_token(self) -> None:
        """Test that invalid token raises 401."""
        mock_request = MagicMock()
        mock_request.headers.get.side_effect = lambda key: {
            "Authorization": "Bearer invalid_token",
            "X-Tenant-ID": "tenant_123",
        }.get(key)

        with (
            patch("ee.onyx.server.tenants.proxy.DATA_PLANE_SECRET", "test_secret"),
            patch("ee.onyx.server.tenants.proxy.jwt.decode") as mock_decode,
        ):
            mock_decode.side_effect = jwt.InvalidTokenError()

            with pytest.raises(HTTPException) as exc_info:
                await verify_self_hosted_token(mock_request)

            assert exc_info.value.status_code == 401
            assert "Invalid token" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_missing_tenant_id(self) -> None:
        """Test that missing X-Tenant-ID raises 400."""
        mock_request = MagicMock()
        mock_request.headers.get.side_effect = lambda key: {
            "Authorization": "Bearer valid_token",
            "X-Tenant-ID": None,
        }.get(key)

        with (
            patch("ee.onyx.server.tenants.proxy.DATA_PLANE_SECRET", "test_secret"),
            patch("ee.onyx.server.tenants.proxy.jwt.decode") as mock_decode,
        ):
            mock_decode.return_value = {"sub": "test"}

            with pytest.raises(HTTPException) as exc_info:
                await verify_self_hosted_token(mock_request)

            assert exc_info.value.status_code == 400
            assert "Missing X-Tenant-ID header" in str(exc_info.value.detail)


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
