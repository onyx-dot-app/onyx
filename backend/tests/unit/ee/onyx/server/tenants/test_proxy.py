"""Tests for proxy endpoints for self-hosted data planes."""

from datetime import datetime
from datetime import timedelta
from datetime import timezone
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import httpx
import pytest
from fastapi import HTTPException

from ee.onyx.server.license.models import LicensePayload
from ee.onyx.server.license.models import PlanType
from ee.onyx.server.tenants.proxy import _check_license_enforcement_enabled
from ee.onyx.server.tenants.proxy import _extract_license_from_header
from ee.onyx.server.tenants.proxy import forward_to_control_plane
from ee.onyx.server.tenants.proxy import get_license_payload
from ee.onyx.server.tenants.proxy import get_license_payload_allow_expired
from ee.onyx.server.tenants.proxy import get_optional_license_payload
from ee.onyx.server.tenants.proxy import verify_license_auth


# All tests that use license auth need LICENSE_ENFORCEMENT_ENABLED=True
LICENSE_ENABLED_PATCH = patch(
    "ee.onyx.server.tenants.proxy.LICENSE_ENFORCEMENT_ENABLED", True
)


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


class TestLicenseEnforcementCheck:
    """Tests for _check_license_enforcement_enabled function."""

    def test_raises_when_disabled(self) -> None:
        """Test that 501 is raised when LICENSE_ENFORCEMENT_ENABLED=False."""
        with patch("ee.onyx.server.tenants.proxy.LICENSE_ENFORCEMENT_ENABLED", False):
            with pytest.raises(HTTPException) as exc_info:
                _check_license_enforcement_enabled()

            assert exc_info.value.status_code == 501
            assert "cloud data plane" in str(exc_info.value.detail).lower()

    def test_passes_when_enabled(self) -> None:
        """Test that no exception is raised when LICENSE_ENFORCEMENT_ENABLED=True."""
        with patch("ee.onyx.server.tenants.proxy.LICENSE_ENFORCEMENT_ENABLED", True):
            _check_license_enforcement_enabled()  # Should not raise


class TestExtractLicenseFromHeader:
    """Tests for _extract_license_from_header helper function."""

    def test_valid_bearer_token(self) -> None:
        """Test extraction of valid Bearer token."""
        result = _extract_license_from_header("Bearer license_data_here", required=True)
        assert result == "license_data_here"

    def test_bearer_with_spaces_in_token(self) -> None:
        """Test that token with spaces is handled correctly (splits on first space only)."""
        result = _extract_license_from_header("Bearer token with spaces", required=True)
        assert result == "token with spaces"

    def test_missing_header_required(self) -> None:
        """Test that missing header raises 401 when required."""
        with pytest.raises(HTTPException) as exc_info:
            _extract_license_from_header(None, required=True)
        assert exc_info.value.status_code == 401

    def test_missing_header_optional(self) -> None:
        """Test that missing header returns None when not required."""
        result = _extract_license_from_header(None, required=False)
        assert result is None

    def test_non_bearer_required(self) -> None:
        """Test that non-Bearer auth raises 401 when required."""
        with pytest.raises(HTTPException) as exc_info:
            _extract_license_from_header("Basic sometoken", required=True)
        assert exc_info.value.status_code == 401

    def test_non_bearer_optional(self) -> None:
        """Test that non-Bearer auth returns None when not required."""
        result = _extract_license_from_header("Basic sometoken", required=False)
        assert result is None

    def test_empty_string_required(self) -> None:
        """Test that empty string raises 401 when required."""
        with pytest.raises(HTTPException) as exc_info:
            _extract_license_from_header("", required=True)
        assert exc_info.value.status_code == 401


class TestVerifyLicenseAuth:
    """Tests for verify_license_auth function."""

    def test_valid_license(self) -> None:
        """Test that a valid license passes verification."""
        payload = make_license_payload()

        with (
            LICENSE_ENABLED_PATCH,
            patch(
                "ee.onyx.server.tenants.proxy.verify_license_signature"
            ) as mock_verify,
        ):
            mock_verify.return_value = payload

            result = verify_license_auth("valid_license_data", allow_expired=False)

            assert result == payload
            mock_verify.assert_called_once_with("valid_license_data")

    def test_invalid_signature(self) -> None:
        """Test that invalid signature raises 401."""
        with (
            LICENSE_ENABLED_PATCH,
            patch(
                "ee.onyx.server.tenants.proxy.verify_license_signature"
            ) as mock_verify,
        ):
            mock_verify.side_effect = ValueError("Invalid signature")

            with pytest.raises(HTTPException) as exc_info:
                verify_license_auth("bad_license", allow_expired=False)

            assert exc_info.value.status_code == 401
            assert "Invalid license" in str(exc_info.value.detail)

    def test_expired_license_rejected(self) -> None:
        """Test that expired license raises 401 when not allowed."""
        payload = make_license_payload(expired=True)

        with (
            LICENSE_ENABLED_PATCH,
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
            LICENSE_ENABLED_PATCH,
            patch(
                "ee.onyx.server.tenants.proxy.verify_license_signature"
            ) as mock_verify,
            patch("ee.onyx.server.tenants.proxy.is_license_valid") as mock_valid,
        ):
            mock_verify.return_value = payload
            mock_valid.return_value = False

            result = verify_license_auth("expired_license", allow_expired=True)

            assert result == payload

    def test_raises_501_when_enforcement_disabled(self) -> None:
        """Test that 501 is raised when LICENSE_ENFORCEMENT_ENABLED=False."""
        with patch("ee.onyx.server.tenants.proxy.LICENSE_ENFORCEMENT_ENABLED", False):
            with pytest.raises(HTTPException) as exc_info:
                verify_license_auth("any_license", allow_expired=False)

            assert exc_info.value.status_code == 501


class TestGetLicensePayload:
    """Tests for get_license_payload dependency."""

    @pytest.mark.asyncio
    async def test_valid_license(self) -> None:
        """Test that valid license returns payload."""
        payload = make_license_payload()

        with (
            LICENSE_ENABLED_PATCH,
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
        with LICENSE_ENABLED_PATCH:
            with pytest.raises(HTTPException) as exc_info:
                await get_license_payload(None)

            assert exc_info.value.status_code == 401
            assert "Missing or invalid authorization header" in str(
                exc_info.value.detail
            )

    @pytest.mark.asyncio
    async def test_invalid_auth_format(self) -> None:
        """Test that non-Bearer auth raises 401."""
        with LICENSE_ENABLED_PATCH:
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
            LICENSE_ENABLED_PATCH,
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
        with LICENSE_ENABLED_PATCH:
            with pytest.raises(HTTPException) as exc_info:
                await get_license_payload_allow_expired(None)

            assert exc_info.value.status_code == 401


class TestGetOptionalLicensePayload:
    """Tests for get_optional_license_payload dependency."""

    @pytest.mark.asyncio
    async def test_no_auth_returns_none(self) -> None:
        """Test that missing auth returns None (for new customers)."""
        with LICENSE_ENABLED_PATCH:
            result = await get_optional_license_payload(None)
            assert result is None

    @pytest.mark.asyncio
    async def test_non_bearer_returns_none(self) -> None:
        """Test that non-Bearer auth returns None."""
        with LICENSE_ENABLED_PATCH:
            result = await get_optional_license_payload("Basic sometoken")
            assert result is None

    @pytest.mark.asyncio
    async def test_valid_license_returns_payload(self) -> None:
        """Test that valid license returns payload."""
        payload = make_license_payload()

        with (
            LICENSE_ENABLED_PATCH,
            patch(
                "ee.onyx.server.tenants.proxy.verify_license_signature"
            ) as mock_verify,
        ):
            mock_verify.return_value = payload

            result = await get_optional_license_payload("Bearer valid_license")

            assert result == payload

    @pytest.mark.asyncio
    async def test_raises_501_when_enforcement_disabled(self) -> None:
        """Test that 501 is raised when LICENSE_ENFORCEMENT_ENABLED=False."""
        with patch("ee.onyx.server.tenants.proxy.LICENSE_ENFORCEMENT_ENABLED", False):
            with pytest.raises(HTTPException) as exc_info:
                await get_optional_license_payload(None)

            assert exc_info.value.status_code == 501


class TestForwardToControlPlane:
    """Tests for forward_to_control_plane function."""

    @pytest.mark.asyncio
    async def test_successful_get_request(self) -> None:
        """Test successful GET request forwarding."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "test"}
        mock_response.raise_for_status = MagicMock()

        with (
            patch(
                "ee.onyx.server.tenants.proxy.generate_data_plane_token"
            ) as mock_token,
            patch("ee.onyx.server.tenants.proxy.httpx.AsyncClient") as mock_client,
            patch(
                "ee.onyx.server.tenants.proxy.CONTROL_PLANE_API_BASE_URL",
                "https://control.example.com",
            ),
        ):
            mock_token.return_value = "cp_token"
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = await forward_to_control_plane(
                "GET", "/test-endpoint", params={"key": "value"}
            )

            assert result == {"data": "test"}

    @pytest.mark.asyncio
    async def test_successful_post_request(self) -> None:
        """Test successful POST request forwarding."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"url": "https://checkout.stripe.com"}
        mock_response.raise_for_status = MagicMock()

        with (
            patch(
                "ee.onyx.server.tenants.proxy.generate_data_plane_token"
            ) as mock_token,
            patch("ee.onyx.server.tenants.proxy.httpx.AsyncClient") as mock_client,
            patch(
                "ee.onyx.server.tenants.proxy.CONTROL_PLANE_API_BASE_URL",
                "https://control.example.com",
            ),
        ):
            mock_token.return_value = "cp_token"
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await forward_to_control_plane(
                "POST", "/create-checkout-session", body={"tenant_id": "t1"}
            )

            assert result == {"url": "https://checkout.stripe.com"}

    @pytest.mark.asyncio
    async def test_http_error_with_detail(self) -> None:
        """Test HTTP error handling with detail from response."""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.json.return_value = {"detail": "Tenant not found"}
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Not Found",
            request=MagicMock(),
            response=mock_response,
        )

        with (
            patch(
                "ee.onyx.server.tenants.proxy.generate_data_plane_token"
            ) as mock_token,
            patch("ee.onyx.server.tenants.proxy.httpx.AsyncClient") as mock_client,
            patch(
                "ee.onyx.server.tenants.proxy.CONTROL_PLANE_API_BASE_URL",
                "https://control.example.com",
            ),
        ):
            mock_token.return_value = "cp_token"
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            with pytest.raises(HTTPException) as exc_info:
                await forward_to_control_plane("GET", "/billing-information")

            assert exc_info.value.status_code == 404
            assert "Tenant not found" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_connection_error(self) -> None:
        """Test connection error handling."""
        with (
            patch(
                "ee.onyx.server.tenants.proxy.generate_data_plane_token"
            ) as mock_token,
            patch("ee.onyx.server.tenants.proxy.httpx.AsyncClient") as mock_client,
            patch(
                "ee.onyx.server.tenants.proxy.CONTROL_PLANE_API_BASE_URL",
                "https://control.example.com",
            ),
        ):
            mock_token.return_value = "cp_token"
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                side_effect=httpx.RequestError("Connection refused")
            )

            with pytest.raises(HTTPException) as exc_info:
                await forward_to_control_plane("GET", "/test")

            assert exc_info.value.status_code == 502
            assert "Failed to connect to control plane" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_follows_redirects(self) -> None:
        """Test that AsyncClient is created with follow_redirects=True.

        The control plane may sit behind a reverse proxy that returns
        308 (HTTP→HTTPS). httpx does not follow redirects by default,
        so we must explicitly opt in.
        """
        mock_response = MagicMock()
        mock_response.json.return_value = {"ok": True}
        mock_response.raise_for_status = MagicMock()

        with (
            patch(
                "ee.onyx.server.tenants.proxy.generate_data_plane_token"
            ) as mock_token,
            patch("ee.onyx.server.tenants.proxy.httpx.AsyncClient") as mock_client,
            patch(
                "ee.onyx.server.tenants.proxy.CONTROL_PLANE_API_BASE_URL",
                "http://control.example.com",
            ),
        ):
            mock_token.return_value = "cp_token"
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            await forward_to_control_plane("GET", "/test")

            mock_client.assert_called_once_with(timeout=30.0, follow_redirects=True)

    @pytest.mark.asyncio
    async def test_unsupported_method(self) -> None:
        """Test that unsupported HTTP methods raise ValueError."""
        with (
            patch(
                "ee.onyx.server.tenants.proxy.generate_data_plane_token"
            ) as mock_token,
            patch("ee.onyx.server.tenants.proxy.httpx.AsyncClient"),
            patch(
                "ee.onyx.server.tenants.proxy.CONTROL_PLANE_API_BASE_URL",
                "https://control.example.com",
            ),
        ):
            mock_token.return_value = "cp_token"

            with pytest.raises(ValueError, match="Unsupported HTTP method"):
                await forward_to_control_plane("DELETE", "/test")


class TestProxyCheckoutSessionWithSeats:
    """Tests for proxy checkout session with seats parameter."""

    @pytest.mark.asyncio
    async def test_includes_seats_in_body_when_provided(self) -> None:
        """Should include seats in request body when provided."""
        from ee.onyx.server.tenants.proxy import proxy_create_checkout_session
        from ee.onyx.server.tenants.proxy import CreateCheckoutSessionRequest

        mock_response = MagicMock()
        mock_response.json.return_value = {"url": "https://checkout.stripe.com/session"}
        mock_response.raise_for_status = MagicMock()

        license_payload = make_license_payload()

        with (
            LICENSE_ENABLED_PATCH,
            patch(
                "ee.onyx.server.tenants.proxy.generate_data_plane_token"
            ) as mock_token,
            patch("ee.onyx.server.tenants.proxy.httpx.AsyncClient") as mock_client,
            patch(
                "ee.onyx.server.tenants.proxy.CONTROL_PLANE_API_BASE_URL",
                "https://control.example.com",
            ),
        ):
            mock_token.return_value = "cp_token"
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post

            request = CreateCheckoutSessionRequest(
                billing_period="monthly",
                seats=25,
                email="test@example.com",
            )
            await proxy_create_checkout_session(
                request_body=request,
                license_payload=license_payload,
            )

            # Verify seats was included in the body
            call_kwargs = mock_post.call_args[1]
            body = call_kwargs["json"]
            assert body["seats"] == 25
            assert body["billing_period"] == "monthly"
            assert body["email"] == "test@example.com"
            assert body["tenant_id"] == "tenant_123"

    @pytest.mark.asyncio
    async def test_excludes_seats_when_not_provided(self) -> None:
        """Should not include seats in request body when not provided."""
        from ee.onyx.server.tenants.proxy import proxy_create_checkout_session
        from ee.onyx.server.tenants.proxy import CreateCheckoutSessionRequest

        mock_response = MagicMock()
        mock_response.json.return_value = {"url": "https://checkout.stripe.com/session"}
        mock_response.raise_for_status = MagicMock()

        license_payload = make_license_payload()

        with (
            LICENSE_ENABLED_PATCH,
            patch(
                "ee.onyx.server.tenants.proxy.generate_data_plane_token"
            ) as mock_token,
            patch("ee.onyx.server.tenants.proxy.httpx.AsyncClient") as mock_client,
            patch(
                "ee.onyx.server.tenants.proxy.CONTROL_PLANE_API_BASE_URL",
                "https://control.example.com",
            ),
        ):
            mock_token.return_value = "cp_token"
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post

            request = CreateCheckoutSessionRequest(billing_period="annual")
            await proxy_create_checkout_session(
                request_body=request,
                license_payload=license_payload,
            )

            # Verify seats was NOT included in the body
            call_kwargs = mock_post.call_args[1]
            body = call_kwargs["json"]
            assert "seats" not in body
            assert body["billing_period"] == "annual"

    @pytest.mark.asyncio
    async def test_includes_seats_for_new_customer(self) -> None:
        """Should include seats for new customer without license."""
        from ee.onyx.server.tenants.proxy import proxy_create_checkout_session
        from ee.onyx.server.tenants.proxy import CreateCheckoutSessionRequest

        mock_response = MagicMock()
        mock_response.json.return_value = {"url": "https://checkout.stripe.com/session"}
        mock_response.raise_for_status = MagicMock()

        with (
            LICENSE_ENABLED_PATCH,
            patch(
                "ee.onyx.server.tenants.proxy.generate_data_plane_token"
            ) as mock_token,
            patch("ee.onyx.server.tenants.proxy.httpx.AsyncClient") as mock_client,
            patch(
                "ee.onyx.server.tenants.proxy.CONTROL_PLANE_API_BASE_URL",
                "https://control.example.com",
            ),
        ):
            mock_token.return_value = "cp_token"
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post

            request = CreateCheckoutSessionRequest(
                billing_period="monthly",
                seats=10,
            )
            # New customer has no license
            await proxy_create_checkout_session(
                request_body=request,
                license_payload=None,
            )

            # Verify seats was included but no tenant_id
            call_kwargs = mock_post.call_args[1]
            body = call_kwargs["json"]
            assert body["seats"] == 10
            assert "tenant_id" not in body
