from typing import Any

import httpx

from ee.onyx.server.spending_limits.models import (
    EffectiveSpendingLimitsResponse,
    SpendingLimitCard,
    SpendingLimitsResponse,
)
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.test_models import DATestUser

_BASE = f"{API_SERVER_URL}/admin/spending-limits"


class SpendingLimitsManager:
    @staticmethod
    def put_card(
        path: str,
        limits: list[dict[str, Any]],
        user_performing_action: DATestUser,
        enabled: bool = True,
    ) -> httpx.Response:
        """PUT one card, e.g. ``workspace/per-user`` or ``groups/3/per-member``.
        Returns the raw response so a test can assert a rejection."""
        return client.put(
            f"{_BASE}/{path}",
            json={"enabled": enabled, "limits": limits},
            headers=user_performing_action.headers,
            cookies=user_performing_action.cookies,
        )

    @staticmethod
    def set_card(
        path: str,
        limits: list[dict[str, Any]],
        user_performing_action: DATestUser,
    ) -> SpendingLimitCard:
        response = SpendingLimitsManager.put_card(path, limits, user_performing_action)
        response.raise_for_status()
        return SpendingLimitCard.model_validate(response.json())

    @staticmethod
    def get_all(user_performing_action: DATestUser) -> SpendingLimitsResponse:
        response = client.get(
            _BASE,
            headers=user_performing_action.headers,
            cookies=user_performing_action.cookies,
        )
        response.raise_for_status()
        return SpendingLimitsResponse.model_validate(response.json())

    @staticmethod
    def get_effective(
        user_id: str, user_performing_action: DATestUser
    ) -> EffectiveSpendingLimitsResponse:
        response = client.get(
            f"{_BASE}/users/{user_id}/effective",
            headers=user_performing_action.headers,
            cookies=user_performing_action.cookies,
        )
        response.raise_for_status()
        return EffectiveSpendingLimitsResponse.model_validate(response.json())
