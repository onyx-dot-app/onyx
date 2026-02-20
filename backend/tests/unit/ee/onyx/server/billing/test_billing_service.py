"""Tests for the billing service layer."""

from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import httpx
import pytest

from .conftest import make_mock_http_client
from .conftest import make_mock_response
from ee.onyx.server.billing.models import BillingInformationResponse
from ee.onyx.server.billing.models import CreateCheckoutSessionResponse
from ee.onyx.server.billing.models import CreateCustomerPortalSessionResponse
from ee.onyx.server.billing.models import SeatUpdateResponse
from ee.onyx.server.billing.models import SubscriptionStatusResponse
from ee.onyx.server.billing.service import BillingServiceError


class TestMakeBillingRequest:
    """Tests for the _make_billing_request helper."""

    @pytest.mark.asyncio
    @patch("ee.onyx.server.billing.service._get_headers")
    @patch("ee.onyx.server.billing.service._get_base_url")
    async def test_makes_post_request(
        self,
        mock_base_url: MagicMock,
        mock_headers: MagicMock,
    ) -> None:
        """Should make POST request with body."""
        from ee.onyx.server.billing.service import _make_billing_request

        mock_base_url.return_value = "https://api.example.com"
        mock_headers.return_value = {"Authorization": "Bearer token"}
        mock_response = make_mock_response({"success": True})
        mock_client = make_mock_http_client("post", response=mock_response)

        with patch("httpx.AsyncClient", mock_client):
            result = await _make_billing_request(
                method="POST",
                path="/test-endpoint",
                body={"key": "value"},
            )

        assert result == {"success": True}

    @pytest.mark.asyncio
    @patch("ee.onyx.server.billing.service._get_headers")
    @patch("ee.onyx.server.billing.service._get_base_url")
    async def test_makes_get_request(
        self,
        mock_base_url: MagicMock,
        mock_headers: MagicMock,
    ) -> None:
        """Should make GET request with params."""
        from ee.onyx.server.billing.service import _make_billing_request

        mock_base_url.return_value = "https://api.example.com"
        mock_headers.return_value = {"Authorization": "Bearer token"}
        mock_response = make_mock_response({"data": "test"})
        mock_client = make_mock_http_client("get", response=mock_response)

        with patch("httpx.AsyncClient", mock_client):
            result = await _make_billing_request(
                method="GET",
                path="/test-endpoint",
                params={"tenant_id": "123"},
            )

        assert result == {"data": "test"}

    @pytest.mark.asyncio
    @patch("ee.onyx.server.billing.service._get_headers")
    @patch("ee.onyx.server.billing.service._get_base_url")
    async def test_raises_on_http_error(
        self,
        mock_base_url: MagicMock,
        mock_headers: MagicMock,
    ) -> None:
        """Should raise BillingServiceError on HTTP error."""
        from ee.onyx.server.billing.service import _make_billing_request

        mock_base_url.return_value = "https://api.example.com"
        mock_headers.return_value = {}
        mock_response = make_mock_response({"detail": "Bad request"})
        mock_response.status_code = 400
        error = httpx.HTTPStatusError(
            "Error", request=MagicMock(), response=mock_response
        )
        mock_client = make_mock_http_client("post", side_effect=error)

        with patch("httpx.AsyncClient", mock_client):
            with pytest.raises(BillingServiceError) as exc_info:
                await _make_billing_request(
                    method="POST",
                    path="/test",
                    error_message="Test failed",
                )

        assert exc_info.value.status_code == 400
        assert "Bad request" in exc_info.value.message

    @pytest.mark.asyncio
    @patch("ee.onyx.server.billing.service._get_headers")
    @patch("ee.onyx.server.billing.service._get_base_url")
    async def test_follows_redirects(
        self,
        mock_base_url: MagicMock,
        mock_headers: MagicMock,
    ) -> None:
        """AsyncClient must be created with follow_redirects=True.

        The target server (cloud data plane for self-hosted, control
        plane for cloud) may sit behind nginx that returns 308
        (HTTP→HTTPS). httpx does not follow redirects by default,
        so we must explicitly opt in.
        """
        from ee.onyx.server.billing.service import _make_billing_request

        mock_base_url.return_value = "http://api.example.com"
        mock_headers.return_value = {"Authorization": "Bearer token"}
        mock_response = make_mock_response({"ok": True})
        mock_client = make_mock_http_client("get", response=mock_response)

        with patch("httpx.AsyncClient", mock_client):
            await _make_billing_request(method="GET", path="/test")

        mock_client.assert_called_once_with(timeout=30.0, follow_redirects=True)

    @pytest.mark.asyncio
    @patch("ee.onyx.server.billing.service._get_headers")
    @patch("ee.onyx.server.billing.service._get_base_url")
    async def test_raises_on_connection_error(
        self,
        mock_base_url: MagicMock,
        mock_headers: MagicMock,
    ) -> None:
        """Should raise BillingServiceError on connection error."""
        from ee.onyx.server.billing.service import _make_billing_request

        mock_base_url.return_value = "https://api.example.com"
        mock_headers.return_value = {}
        error = httpx.RequestError("Connection failed")
        mock_client = make_mock_http_client("post", side_effect=error)

        with patch("httpx.AsyncClient", mock_client):
            with pytest.raises(BillingServiceError) as exc_info:
                await _make_billing_request(method="POST", path="/test")

        assert exc_info.value.status_code == 502
        assert "Failed to connect" in exc_info.value.message


class TestCreateCheckoutSession:
    """Tests for create_checkout_session service function."""

    @pytest.mark.asyncio
    @patch("ee.onyx.server.billing.service._make_billing_request")
    async def test_creates_checkout_session(
        self,
        mock_request: AsyncMock,
    ) -> None:
        """Should create checkout session and return URL."""
        from ee.onyx.server.billing.service import create_checkout_session

        mock_request.return_value = {"url": "https://checkout.stripe.com/session"}

        result = await create_checkout_session(
            billing_period="monthly",
            email="test@example.com",
            license_data="license_blob",
            redirect_url="https://app.example.com/success",
        )

        assert isinstance(result, CreateCheckoutSessionResponse)
        assert result.stripe_checkout_url == "https://checkout.stripe.com/session"

        call_kwargs = mock_request.call_args[1]
        assert call_kwargs["method"] == "POST"
        assert call_kwargs["path"] == "/create-checkout-session"
        assert call_kwargs["body"]["billing_period"] == "monthly"
        assert call_kwargs["body"]["email"] == "test@example.com"


class TestCreateCustomerPortalSession:
    """Tests for create_customer_portal_session service function."""

    @pytest.mark.asyncio
    @patch("ee.onyx.server.billing.service._make_billing_request")
    async def test_creates_portal_session(
        self,
        mock_request: AsyncMock,
    ) -> None:
        """Should create portal session and return URL."""
        from ee.onyx.server.billing.service import create_customer_portal_session

        mock_request.return_value = {"url": "https://billing.stripe.com/portal"}

        result = await create_customer_portal_session(
            license_data="license_blob",
            return_url="https://app.example.com/billing",
        )

        assert isinstance(result, CreateCustomerPortalSessionResponse)
        assert result.stripe_customer_portal_url == "https://billing.stripe.com/portal"


class TestGetBillingInformation:
    """Tests for get_billing_information service function."""

    @pytest.mark.asyncio
    @patch("ee.onyx.server.billing.service._make_billing_request")
    async def test_returns_billing_info(
        self,
        mock_request: AsyncMock,
    ) -> None:
        """Should return billing information."""
        from ee.onyx.server.billing.service import get_billing_information

        mock_request.return_value = {
            "tenant_id": "tenant_123",
            "status": "active",
            "seats": 10,
            "billing_period": "monthly",
        }

        result = await get_billing_information(license_data="license_blob")

        assert isinstance(result, BillingInformationResponse)
        assert result.tenant_id == "tenant_123"
        assert result.status == "active"
        assert result.seats == 10

    @pytest.mark.asyncio
    @patch("ee.onyx.server.billing.service._make_billing_request")
    async def test_returns_not_subscribed(
        self,
        mock_request: AsyncMock,
    ) -> None:
        """Should return SubscriptionStatusResponse when not subscribed."""
        from ee.onyx.server.billing.service import get_billing_information

        mock_request.return_value = {"subscribed": False}

        result = await get_billing_information(license_data="license_blob")

        assert isinstance(result, SubscriptionStatusResponse)
        assert result.subscribed is False


class TestUpdateSeatCount:
    """Tests for update_seat_count service function."""

    @pytest.mark.asyncio
    @patch("ee.onyx.server.billing.service._make_billing_request")
    async def test_updates_seats(
        self,
        mock_request: AsyncMock,
    ) -> None:
        """Should update seat count and return response."""
        from ee.onyx.server.billing.service import update_seat_count

        mock_request.return_value = {
            "success": True,
            "current_seats": 15,
            "used_seats": 5,
            "message": "Seats updated to 15",
        }

        result = await update_seat_count(
            new_seat_count=15,
            license_data="license_blob",
        )

        assert isinstance(result, SeatUpdateResponse)
        assert result.success is True
        assert result.current_seats == 15
        assert result.used_seats == 5

        call_kwargs = mock_request.call_args[1]
        assert call_kwargs["body"]["new_seat_count"] == 15

    @pytest.mark.asyncio
    @patch("ee.onyx.server.billing.service._make_billing_request")
    async def test_includes_tenant_id_for_cloud(
        self,
        mock_request: AsyncMock,
    ) -> None:
        """Should include tenant_id in body for cloud deployments."""
        from ee.onyx.server.billing.service import update_seat_count

        mock_request.return_value = {
            "success": True,
            "current_seats": 10,
            "used_seats": 5,
        }

        with patch("ee.onyx.server.billing.service.MULTI_TENANT", True):
            await update_seat_count(
                new_seat_count=10,
                tenant_id="tenant_123",
            )

        call_kwargs = mock_request.call_args[1]
        assert call_kwargs["body"]["tenant_id"] == "tenant_123"
