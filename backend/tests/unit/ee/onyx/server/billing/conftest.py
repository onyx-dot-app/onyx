"""Shared fixtures and utilities for billing tests."""

from datetime import datetime
from datetime import timezone
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import pytest

from ee.onyx.server.license.models import LicensePayload
from ee.onyx.server.license.models import PlanType


@pytest.fixture
def mock_license_payload() -> LicensePayload:
    """Create a valid LicensePayload for testing."""
    return make_license_payload()


@pytest.fixture
def mock_expired_license_payload() -> LicensePayload:
    """Create an expired LicensePayload for testing."""
    return make_license_payload(expired=True)


def make_license_payload(
    tenant_id: str = "tenant_123",
    seats: int = 10,
    expired: bool = False,
) -> LicensePayload:
    """Create a LicensePayload for testing.

    Args:
        tenant_id: The tenant ID
        seats: Number of seats
        expired: If True, creates an expired license
    """
    now = datetime.now(timezone.utc)
    expires_at = (
        datetime(2020, 1, 1, tzinfo=timezone.utc)
        if expired
        else datetime(2030, 1, 1, tzinfo=timezone.utc)
    )

    return LicensePayload(
        version="1.0",
        tenant_id=tenant_id,
        issued_at=now,
        expires_at=expires_at,
        seats=seats,
        plan_type=PlanType.MONTHLY,
    )


def make_mock_response(json_data: dict) -> MagicMock:
    """Create a mock httpx response.

    Args:
        json_data: The JSON data to return from response.json()
    """
    mock_response = MagicMock()
    mock_response.json.return_value = json_data
    mock_response.raise_for_status = MagicMock()
    return mock_response


def make_mock_http_client(
    method: str = "post",
    response: MagicMock | None = None,
    side_effect: Exception | None = None,
) -> MagicMock:
    """Create a mock httpx.AsyncClient context manager.

    Args:
        method: HTTP method to mock ("get" or "post")
        response: Mock response to return
        side_effect: Exception to raise instead of returning response
    """
    mock_client = MagicMock()
    mock_method = AsyncMock(return_value=response, side_effect=side_effect)
    setattr(mock_client.return_value.__aenter__.return_value, method, mock_method)
    return mock_client
