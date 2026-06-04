"""Tests for billing API endpoints."""

from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import httpx
import pytest

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError


class TestGetStripePublishableKey:
    """Tests for get_stripe_publishable_key endpoint."""

    def setup_method(self) -> None:
        """Reset the cache before each test."""
        import ee.onyx.server.tenants.billing_api as billing_api

        billing_api._stripe_publishable_key_cache = None

    @pytest.mark.asyncio
    @patch("ee.onyx.server.tenants.billing_api.STRIPE_PUBLISHABLE_KEY_OVERRIDE", None)
    @patch(
        "ee.onyx.server.tenants.billing_api.STRIPE_PUBLISHABLE_KEY_URL",
        "https://example.com/key.txt",
    )
    async def test_fetches_from_s3_when_no_override(self) -> None:
        """Should fetch key from S3 when no env var override is set."""
        from ee.onyx.server.tenants.billing_api import get_stripe_publishable_key

        mock_response = MagicMock()
        mock_response.text = "pk_live_test123"
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )
            result = await get_stripe_publishable_key()

        assert result.publishable_key == "pk_live_test123"

    @pytest.mark.asyncio
    @patch(
        "ee.onyx.server.tenants.billing_api.STRIPE_PUBLISHABLE_KEY_OVERRIDE",
        "pk_test_override123",
    )
    async def test_uses_env_var_override_when_set(self) -> None:
        """Should use env var override instead of fetching from S3."""
        from ee.onyx.server.tenants.billing_api import get_stripe_publishable_key

        with patch("httpx.AsyncClient") as mock_client:
            result = await get_stripe_publishable_key()
            # Should not call S3
            mock_client.assert_not_called()

        assert result.publishable_key == "pk_test_override123"

    @pytest.mark.asyncio
    @patch(
        "ee.onyx.server.tenants.billing_api.STRIPE_PUBLISHABLE_KEY_OVERRIDE",
        "invalid_key",
    )
    async def test_rejects_invalid_env_var_key_format(self) -> None:
        """Should reject keys that don't start with pk_."""
        from ee.onyx.server.tenants.billing_api import get_stripe_publishable_key

        with pytest.raises(OnyxError) as exc_info:
            await get_stripe_publishable_key()

        assert exc_info.value.status_code == 500
        assert exc_info.value.error_code is OnyxErrorCode.INTERNAL_ERROR
        assert exc_info.value.detail == "Invalid Stripe publishable key format"

    @pytest.mark.asyncio
    @patch("ee.onyx.server.tenants.billing_api.STRIPE_PUBLISHABLE_KEY_OVERRIDE", None)
    @patch(
        "ee.onyx.server.tenants.billing_api.STRIPE_PUBLISHABLE_KEY_URL",
        "https://example.com/key.txt",
    )
    async def test_rejects_invalid_s3_key_format(self) -> None:
        """Should reject keys from S3 that don't start with pk_."""
        from ee.onyx.server.tenants.billing_api import get_stripe_publishable_key

        mock_response = MagicMock()
        mock_response.text = "invalid_key"
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )
            with pytest.raises(OnyxError) as exc_info:
                await get_stripe_publishable_key()

        assert exc_info.value.status_code == 500
        assert exc_info.value.error_code is OnyxErrorCode.INTERNAL_ERROR
        assert exc_info.value.detail == "Invalid Stripe publishable key format"

    @pytest.mark.asyncio
    @patch("ee.onyx.server.tenants.billing_api.STRIPE_PUBLISHABLE_KEY_OVERRIDE", None)
    @patch(
        "ee.onyx.server.tenants.billing_api.STRIPE_PUBLISHABLE_KEY_URL",
        "https://example.com/key.txt",
    )
    async def test_handles_s3_fetch_error(self) -> None:
        """Should return error when S3 fetch fails."""
        from ee.onyx.server.tenants.billing_api import get_stripe_publishable_key

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                side_effect=httpx.HTTPError("Connection failed")
            )
            with pytest.raises(OnyxError) as exc_info:
                await get_stripe_publishable_key()

        assert exc_info.value.status_code == 500
        assert exc_info.value.error_code is OnyxErrorCode.INTERNAL_ERROR
        assert exc_info.value.detail == "Failed to fetch Stripe publishable key"

    @pytest.mark.asyncio
    @patch("ee.onyx.server.tenants.billing_api.STRIPE_PUBLISHABLE_KEY_OVERRIDE", None)
    @patch("ee.onyx.server.tenants.billing_api.STRIPE_PUBLISHABLE_KEY_URL", None)
    async def test_error_when_no_config(self) -> None:
        """Should return error when neither env var nor S3 URL is configured."""
        from ee.onyx.server.tenants.billing_api import get_stripe_publishable_key

        with pytest.raises(OnyxError) as exc_info:
            await get_stripe_publishable_key()

        assert exc_info.value.status_code == 500
        assert exc_info.value.error_code is OnyxErrorCode.INTERNAL_ERROR
        assert "not configured" in exc_info.value.detail

    @pytest.mark.asyncio
    @patch(
        "ee.onyx.server.tenants.billing_api.STRIPE_PUBLISHABLE_KEY_OVERRIDE",
        "pk_test_cached",
    )
    async def test_caches_key_after_first_fetch(self) -> None:
        """Should cache the key and return it on subsequent calls."""
        from ee.onyx.server.tenants.billing_api import get_stripe_publishable_key

        # First call
        result1 = await get_stripe_publishable_key()
        assert result1.publishable_key == "pk_test_cached"

        # Second call - should use cache even if we change the override
        with patch(
            "ee.onyx.server.tenants.billing_api.STRIPE_PUBLISHABLE_KEY_OVERRIDE",
            "pk_test_different",
        ):
            result2 = await get_stripe_publishable_key()
            # Should still return cached value
            assert result2.publishable_key == "pk_test_cached"


class TestCreateSubscriptionSession:
    """Tests for create_subscription_session endpoint."""

    @pytest.mark.asyncio
    async def test_returns_session_id_and_url_for_new_checkout(self) -> None:
        """New-subscription checkout returns both sessionId and a hosted url."""
        from ee.onyx.server.tenants.billing_api import create_subscription_session
        from ee.onyx.server.tenants.models import StripeCheckoutSessionResult
        from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

        token = CURRENT_TENANT_ID_CONTEXTVAR.set("tenant_123")
        try:
            with patch(
                "ee.onyx.server.tenants.billing_api.fetch_stripe_checkout_session",
                return_value=StripeCheckoutSessionResult(
                    session_id="cs_test_123",
                    url="https://checkout.stripe.com/session",
                ),
            ):
                result = await create_subscription_session(request=None, _=MagicMock())
        finally:
            CURRENT_TENANT_ID_CONTEXTVAR.reset(token)

        assert result.sessionId == "cs_test_123"
        assert result.url == "https://checkout.stripe.com/session"
        assert result.requires_payment_method_update is False

    @pytest.mark.asyncio
    async def test_handles_past_due_portal_response(self) -> None:
        """past_due/unpaid tenants get a portal url with a null sessionId.

        Regression: the response model used to require a non-null sessionId,
        so this branch raised a ValidationError -> 500 on the Access Restricted
        page (the control plane routes lapsed subs to the payment-update portal).
        """
        from ee.onyx.server.tenants.billing_api import create_subscription_session
        from ee.onyx.server.tenants.models import StripeCheckoutSessionResult
        from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

        token = CURRENT_TENANT_ID_CONTEXTVAR.set("tenant_123")
        try:
            with patch(
                "ee.onyx.server.tenants.billing_api.fetch_stripe_checkout_session",
                return_value=StripeCheckoutSessionResult(
                    session_id=None,
                    url="https://billing.stripe.com/portal",
                    requires_payment_method_update=True,
                ),
            ):
                result = await create_subscription_session(request=None, _=MagicMock())
        finally:
            CURRENT_TENANT_ID_CONTEXTVAR.reset(token)

        assert result.sessionId is None
        assert result.url == "https://billing.stripe.com/portal"
        assert result.requires_payment_method_update is True

    @pytest.mark.asyncio
    async def test_wraps_upstream_failure_as_internal_error(self) -> None:
        """Upstream failures surface as INTERNAL_ERROR, not an unhandled crash."""
        from ee.onyx.server.tenants.billing_api import create_subscription_session
        from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

        token = CURRENT_TENANT_ID_CONTEXTVAR.set("tenant_123")
        try:
            with patch(
                "ee.onyx.server.tenants.billing_api.fetch_stripe_checkout_session",
                side_effect=Exception("control plane 409"),
            ):
                with pytest.raises(OnyxError) as exc_info:
                    await create_subscription_session(request=None, _=MagicMock())
        finally:
            CURRENT_TENANT_ID_CONTEXTVAR.reset(token)

        assert exc_info.value.error_code is OnyxErrorCode.INTERNAL_ERROR


class TestFetchStripeCheckoutSession:
    """Tests for the control-plane checkout-session proxy."""

    def test_raises_when_control_plane_returns_no_url(self) -> None:
        """A success response without a url is a contract violation, not silent."""
        from ee.onyx.server.tenants.billing import fetch_stripe_checkout_session

        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {"sessionId": "cs_test_123"}

        with (
            patch(
                "ee.onyx.server.tenants.billing.generate_data_plane_token",
                return_value="cp_token",
            ),
            patch(
                "ee.onyx.server.tenants.billing.requests.post",
                return_value=mock_response,
            ),
        ):
            with pytest.raises(Exception, match="no checkout URL"):
                fetch_stripe_checkout_session("tenant_123")

    def test_returns_full_result(self) -> None:
        """Parses sessionId, url, and the payment-method-update flag."""
        from ee.onyx.server.tenants.billing import fetch_stripe_checkout_session

        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {
            "sessionId": None,
            "url": "https://billing.stripe.com/portal",
            "requires_payment_method_update": True,
        }

        with (
            patch(
                "ee.onyx.server.tenants.billing.generate_data_plane_token",
                return_value="cp_token",
            ),
            patch(
                "ee.onyx.server.tenants.billing.requests.post",
                return_value=mock_response,
            ),
        ):
            result = fetch_stripe_checkout_session("tenant_123")

        assert result.session_id is None
        assert result.url == "https://billing.stripe.com/portal"
        assert result.requires_payment_method_update is True
