"""Tests for the unified billing API endpoints."""

from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from ee.onyx.server.billing.models import BillingInformationResponse
from ee.onyx.server.billing.models import CreateCheckoutSessionResponse
from ee.onyx.server.billing.models import CreateCustomerPortalSessionResponse
from ee.onyx.server.billing.models import SeatUpdateResponse
from ee.onyx.server.billing.models import SubscriptionStatusResponse
from ee.onyx.server.billing.service import BillingServiceError


class TestCreateCheckoutSession:
    """Tests for create_checkout_session endpoint."""

    @pytest.mark.asyncio
    @patch("ee.onyx.server.billing.api.create_checkout_service")
    @patch("ee.onyx.server.billing.api._get_tenant_id")
    @patch("ee.onyx.server.billing.api._get_license_data")
    async def test_creates_checkout_session_cloud(
        self,
        mock_get_license: MagicMock,
        mock_get_tenant: MagicMock,
        mock_service: AsyncMock,
    ) -> None:
        """Should create checkout session for cloud deployment."""
        from ee.onyx.server.billing.api import create_checkout_session
        from ee.onyx.server.billing.models import CreateCheckoutSessionRequest

        mock_get_license.return_value = None
        mock_get_tenant.return_value = "tenant_123"
        mock_service.return_value = CreateCheckoutSessionResponse(
            stripe_checkout_url="https://checkout.stripe.com/session"
        )

        request = CreateCheckoutSessionRequest(billing_period="monthly")
        result = await create_checkout_session(
            request=request, _=MagicMock(), db_session=MagicMock()
        )

        assert result.stripe_checkout_url == "https://checkout.stripe.com/session"
        mock_service.assert_called_once()

    @pytest.mark.asyncio
    @patch("ee.onyx.server.billing.api.create_checkout_service")
    @patch("ee.onyx.server.billing.api._get_tenant_id")
    @patch("ee.onyx.server.billing.api._get_license_data")
    async def test_creates_checkout_session_self_hosted(
        self,
        mock_get_license: MagicMock,
        mock_get_tenant: MagicMock,
        mock_service: AsyncMock,
    ) -> None:
        """Should create checkout session for self-hosted with license."""
        from ee.onyx.server.billing.api import create_checkout_session
        from ee.onyx.server.billing.models import CreateCheckoutSessionRequest

        mock_get_license.return_value = "license_data_blob"
        mock_get_tenant.return_value = None
        mock_service.return_value = CreateCheckoutSessionResponse(
            stripe_checkout_url="https://checkout.stripe.com/session"
        )

        request = CreateCheckoutSessionRequest(
            billing_period="annual", email="test@example.com"
        )
        result = await create_checkout_session(
            request=request, _=MagicMock(), db_session=MagicMock()
        )

        assert result.stripe_checkout_url == "https://checkout.stripe.com/session"
        call_kwargs = mock_service.call_args[1]
        assert call_kwargs["billing_period"] == "annual"
        assert call_kwargs["email"] == "test@example.com"
        assert call_kwargs["license_data"] == "license_data_blob"

    @pytest.mark.asyncio
    @patch("ee.onyx.server.billing.api.create_checkout_service")
    @patch("ee.onyx.server.billing.api._get_tenant_id")
    @patch("ee.onyx.server.billing.api._get_license_data")
    async def test_raises_on_service_error(
        self,
        mock_get_license: MagicMock,
        mock_get_tenant: MagicMock,
        mock_service: AsyncMock,
    ) -> None:
        """Should raise HTTPException when service fails."""
        from fastapi import HTTPException

        from ee.onyx.server.billing.api import create_checkout_session

        mock_get_license.return_value = None
        mock_get_tenant.return_value = "tenant_123"
        mock_service.side_effect = BillingServiceError("Stripe error", 502)

        with pytest.raises(HTTPException) as exc_info:
            await create_checkout_session(
                request=None, _=MagicMock(), db_session=MagicMock()
            )

        assert exc_info.value.status_code == 502
        assert "Stripe error" in exc_info.value.detail


class TestCreateCustomerPortalSession:
    """Tests for create_customer_portal_session endpoint."""

    @pytest.mark.asyncio
    @patch("ee.onyx.server.billing.api.MULTI_TENANT", False)
    @patch("ee.onyx.server.billing.api.create_portal_service")
    @patch("ee.onyx.server.billing.api._get_tenant_id")
    @patch("ee.onyx.server.billing.api._get_license_data")
    async def test_requires_license_for_self_hosted(
        self,
        mock_get_license: MagicMock,
        mock_get_tenant: MagicMock,
        mock_service: AsyncMock,
    ) -> None:
        """Should reject self-hosted without license."""
        from fastapi import HTTPException

        from ee.onyx.server.billing.api import create_customer_portal_session

        mock_get_license.return_value = None
        mock_get_tenant.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await create_customer_portal_session(
                request=None, _=MagicMock(), db_session=MagicMock()
            )

        assert exc_info.value.status_code == 400
        assert "No license found" in exc_info.value.detail

    @pytest.mark.asyncio
    @patch("ee.onyx.server.billing.api.create_portal_service")
    @patch("ee.onyx.server.billing.api._get_tenant_id")
    @patch("ee.onyx.server.billing.api._get_license_data")
    async def test_creates_portal_session(
        self,
        mock_get_license: MagicMock,
        mock_get_tenant: MagicMock,
        mock_service: AsyncMock,
    ) -> None:
        """Should create portal session with valid license."""
        from ee.onyx.server.billing.api import create_customer_portal_session

        mock_get_license.return_value = "license_blob"
        mock_get_tenant.return_value = None
        mock_service.return_value = CreateCustomerPortalSessionResponse(
            stripe_customer_portal_url="https://billing.stripe.com/portal"
        )

        result = await create_customer_portal_session(
            request=None, _=MagicMock(), db_session=MagicMock()
        )

        assert result.stripe_customer_portal_url == "https://billing.stripe.com/portal"


class TestGetBillingInformation:
    """Tests for get_billing_information endpoint."""

    @pytest.mark.asyncio
    @patch("ee.onyx.server.billing.api.MULTI_TENANT", False)
    @patch("ee.onyx.server.billing.api._get_tenant_id")
    @patch("ee.onyx.server.billing.api._get_license_data")
    async def test_returns_not_subscribed_without_license(
        self,
        mock_get_license: MagicMock,
        mock_get_tenant: MagicMock,
    ) -> None:
        """Should return subscribed=False for self-hosted without license."""
        from ee.onyx.server.billing.api import get_billing_information

        mock_get_license.return_value = None
        mock_get_tenant.return_value = None

        result = await get_billing_information(_=MagicMock(), db_session=MagicMock())

        assert isinstance(result, SubscriptionStatusResponse)
        assert result.subscribed is False

    @pytest.mark.asyncio
    @patch("ee.onyx.server.billing.api.get_billing_service")
    @patch("ee.onyx.server.billing.api._get_tenant_id")
    @patch("ee.onyx.server.billing.api._get_license_data")
    async def test_returns_billing_info(
        self,
        mock_get_license: MagicMock,
        mock_get_tenant: MagicMock,
        mock_service: AsyncMock,
    ) -> None:
        """Should return billing information with valid license."""
        from ee.onyx.server.billing.api import get_billing_information

        mock_get_license.return_value = "license_blob"
        mock_get_tenant.return_value = None
        mock_service.return_value = BillingInformationResponse(
            tenant_id="tenant_123",
            status="active",
            seats=10,
        )

        result = await get_billing_information(_=MagicMock(), db_session=MagicMock())

        assert isinstance(result, BillingInformationResponse)
        assert result.tenant_id == "tenant_123"
        assert result.status == "active"
        assert result.seats == 10


class TestUpdateSeats:
    """Tests for update_seats endpoint."""

    @pytest.mark.asyncio
    @patch("ee.onyx.server.billing.api.MULTI_TENANT", False)
    @patch("ee.onyx.server.billing.api._get_tenant_id")
    @patch("ee.onyx.server.billing.api._get_license_data")
    async def test_requires_license_for_self_hosted(
        self,
        mock_get_license: MagicMock,
        mock_get_tenant: MagicMock,
    ) -> None:
        """Should reject self-hosted without license."""
        from fastapi import HTTPException

        from ee.onyx.server.billing.api import update_seats
        from ee.onyx.server.billing.models import SeatUpdateRequest

        mock_get_license.return_value = None
        mock_get_tenant.return_value = None

        request = SeatUpdateRequest(new_seat_count=10)

        with pytest.raises(HTTPException) as exc_info:
            await update_seats(request=request, _=MagicMock(), db_session=MagicMock())

        assert exc_info.value.status_code == 400
        assert "No license found" in exc_info.value.detail

    @pytest.mark.asyncio
    @patch("ee.onyx.server.billing.api.update_seat_service")
    @patch("ee.onyx.server.billing.api._get_tenant_id")
    @patch("ee.onyx.server.billing.api._get_license_data")
    async def test_updates_seats_successfully(
        self,
        mock_get_license: MagicMock,
        mock_get_tenant: MagicMock,
        mock_service: AsyncMock,
    ) -> None:
        """Should update seats with valid license."""
        from ee.onyx.server.billing.api import update_seats
        from ee.onyx.server.billing.models import SeatUpdateRequest

        mock_get_license.return_value = "license_blob"
        mock_get_tenant.return_value = None
        mock_service.return_value = SeatUpdateResponse(
            success=True,
            current_seats=15,
            used_seats=5,
            message="Seats updated to 15",
        )

        request = SeatUpdateRequest(new_seat_count=15)
        result = await update_seats(
            request=request, _=MagicMock(), db_session=MagicMock()
        )

        assert result.success is True
        assert result.current_seats == 15
        assert result.used_seats == 5
        mock_service.assert_called_once_with(
            new_seat_count=15,
            license_data="license_blob",
            tenant_id=None,
        )

    @pytest.mark.asyncio
    @patch("ee.onyx.server.billing.api.update_seat_service")
    @patch("ee.onyx.server.billing.api._get_tenant_id")
    @patch("ee.onyx.server.billing.api._get_license_data")
    async def test_handles_billing_service_error(
        self,
        mock_get_license: MagicMock,
        mock_get_tenant: MagicMock,
        mock_service: AsyncMock,
    ) -> None:
        """Should convert BillingServiceError to HTTPException."""
        from fastapi import HTTPException

        from ee.onyx.server.billing.api import update_seats
        from ee.onyx.server.billing.models import SeatUpdateRequest

        mock_get_license.return_value = "license_blob"
        mock_get_tenant.return_value = None
        mock_service.side_effect = BillingServiceError(
            "Cannot reduce below 10 seats", 400
        )

        request = SeatUpdateRequest(new_seat_count=5)

        with pytest.raises(HTTPException) as exc_info:
            await update_seats(request=request, _=MagicMock(), db_session=MagicMock())

        assert exc_info.value.status_code == 400
        assert "Cannot reduce below 10 seats" in exc_info.value.detail
