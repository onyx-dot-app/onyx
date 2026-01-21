"""Tests for billing API endpoints."""

from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import httpx
import pytest


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
        from fastapi import HTTPException

        from ee.onyx.server.tenants.billing_api import get_stripe_publishable_key

        with pytest.raises(HTTPException) as exc_info:
            await get_stripe_publishable_key()

        assert exc_info.value.status_code == 500
        assert "Invalid Stripe publishable key format" in exc_info.value.detail

    @pytest.mark.asyncio
    @patch("ee.onyx.server.tenants.billing_api.STRIPE_PUBLISHABLE_KEY_OVERRIDE", None)
    @patch(
        "ee.onyx.server.tenants.billing_api.STRIPE_PUBLISHABLE_KEY_URL",
        "https://example.com/key.txt",
    )
    async def test_rejects_invalid_s3_key_format(self) -> None:
        """Should reject keys from S3 that don't start with pk_."""
        from fastapi import HTTPException

        from ee.onyx.server.tenants.billing_api import get_stripe_publishable_key

        mock_response = MagicMock()
        mock_response.text = "invalid_key"
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )
            with pytest.raises(HTTPException) as exc_info:
                await get_stripe_publishable_key()

        assert exc_info.value.status_code == 500
        assert "Invalid Stripe publishable key format" in exc_info.value.detail

    @pytest.mark.asyncio
    @patch("ee.onyx.server.tenants.billing_api.STRIPE_PUBLISHABLE_KEY_OVERRIDE", None)
    @patch(
        "ee.onyx.server.tenants.billing_api.STRIPE_PUBLISHABLE_KEY_URL",
        "https://example.com/key.txt",
    )
    async def test_handles_s3_fetch_error(self) -> None:
        """Should return error when S3 fetch fails."""
        from fastapi import HTTPException

        from ee.onyx.server.tenants.billing_api import get_stripe_publishable_key

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                side_effect=httpx.HTTPError("Connection failed")
            )
            with pytest.raises(HTTPException) as exc_info:
                await get_stripe_publishable_key()

        assert exc_info.value.status_code == 500
        assert "Failed to fetch Stripe publishable key" in exc_info.value.detail

    @pytest.mark.asyncio
    @patch("ee.onyx.server.tenants.billing_api.STRIPE_PUBLISHABLE_KEY_OVERRIDE", None)
    @patch("ee.onyx.server.tenants.billing_api.STRIPE_PUBLISHABLE_KEY_URL", None)
    async def test_error_when_no_config(self) -> None:
        """Should return error when neither env var nor S3 URL is configured."""
        from fastapi import HTTPException

        from ee.onyx.server.tenants.billing_api import get_stripe_publishable_key

        with pytest.raises(HTTPException) as exc_info:
            await get_stripe_publishable_key()

        assert exc_info.value.status_code == 500
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
