import requests

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.constants import GENERAL_HEADERS
from tests.integration.common_utils.test_models import DATestScimToken
from tests.integration.common_utils.test_models import DATestUser


class ScimTokenManager:
    @staticmethod
    def create(
        name: str,
        user_performing_action: DATestUser,
    ) -> DATestScimToken:
        response = requests.post(
            f"{API_SERVER_URL}/admin/enterprise-settings/scim/token",
            json={"name": name},
            headers=user_performing_action.headers,
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()
        return DATestScimToken(
            id=data["id"],
            name=data["name"],
            token_display=data["token_display"],
            is_active=data["is_active"],
            created_at=data["created_at"],
            last_used_at=data.get("last_used_at"),
            raw_token=data["raw_token"],
        )

    @staticmethod
    def get_active(
        user_performing_action: DATestUser,
    ) -> DATestScimToken | None:
        response = requests.get(
            f"{API_SERVER_URL}/admin/enterprise-settings/scim/token",
            headers=user_performing_action.headers,
            timeout=60,
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        data = response.json()
        return DATestScimToken(
            id=data["id"],
            name=data["name"],
            token_display=data["token_display"],
            is_active=data["is_active"],
            created_at=data["created_at"],
            last_used_at=data.get("last_used_at"),
        )

    @staticmethod
    def get_scim_headers(raw_token: str) -> dict[str, str]:
        return {
            **GENERAL_HEADERS,
            "Authorization": f"Bearer {raw_token}",
        }

    @staticmethod
    def scim_get(
        path: str,
        raw_token: str,
    ) -> requests.Response:
        return requests.get(
            f"{API_SERVER_URL}/scim/v2{path}",
            headers=ScimTokenManager.get_scim_headers(raw_token),
            timeout=60,
        )

    @staticmethod
    def scim_get_no_auth(path: str) -> requests.Response:
        return requests.get(
            f"{API_SERVER_URL}/scim/v2{path}",
            headers=GENERAL_HEADERS,
            timeout=60,
        )
