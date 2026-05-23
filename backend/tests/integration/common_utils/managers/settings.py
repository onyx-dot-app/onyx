from typing import Any
from typing import Dict
from typing import Optional

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.test_models import DATestSettings
from tests.integration.common_utils.test_models import DATestUser


class SettingsManager:
    @staticmethod
    def get_settings(
        user_performing_action: DATestUser,
    ) -> tuple[Dict[str, Any], str]:
        headers = user_performing_action.headers
        headers.pop("Content-Type", None)

        response = client.get(
            f"{API_SERVER_URL}/admin/settings",
            headers=headers,
        )

        if response.is_error:
            return (
                {},
                f"Failed to get settings - {response.json().get('detail', 'Unknown error')}",
            )

        return response.json(), ""

    @staticmethod
    def update_settings(
        settings: DATestSettings,
        user_performing_action: DATestUser,
    ) -> tuple[Dict[str, Any], str]:
        headers = user_performing_action.headers
        headers.pop("Content-Type", None)

        payload = settings.model_dump()
        response = client.put(
            f"{API_SERVER_URL}/admin/settings",
            json=payload,
            headers=headers,
        )

        if response.is_error:
            return (
                {},
                f"Failed to update settings - {response.json().get('detail', 'Unknown error')}",
            )

        return response.json(), ""

    @staticmethod
    def get_setting(
        key: str,
        user_performing_action: DATestUser,
    ) -> Optional[Any]:
        settings, error = SettingsManager.get_settings(user_performing_action)
        if error:
            return None
        return settings.get(key)
