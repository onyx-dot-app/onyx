from uuid import uuid4

import requests

from onyx.db.models import UserRole
from onyx.server.api_key.models import APIKeyArgs
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.constants import GENERAL_HEADERS
from tests.integration.common_utils.test_models import DATestAPIKey
from tests.integration.common_utils.test_models import DATestUser


class APIKeyManager:
    @staticmethod
    def create(
        name: str | None = None,
        api_key_role: UserRole = UserRole.ADMIN,
        user_performing_action: DATestUser | None = None,
    ) -> DATestAPIKey:
        name = f"{name}-api-key" if name else f"test-api-key-{uuid4()}"
        api_key_request = APIKeyArgs(
            name=name,
            role=api_key_role,
        )
        api_key_response = requests.post(
            f"{API_SERVER_URL}/admin/api-key",
            json=api_key_request.model_dump(),
            headers=(
                user_performing_action.headers
                if user_performing_action
                else GENERAL_HEADERS
            ),
        )
        api_key_response.raise_for_status()
        api_key = api_key_response.json()
        result_api_key = DATestAPIKey(
            api_key_id=api_key["api_key_id"],
            api_key_display=api_key["api_key_display"],
            api_key=api_key["api_key"],
            api_key_name=name,
            api_key_role=api_key_role,
            user_id=api_key["user_id"],
            headers=GENERAL_HEADERS,
        )
        result_api_key.headers["Authorization"] = f"Bearer {result_api_key.api_key}"
        return result_api_key

    @staticmethod
    def delete(
        api_key: DATestAPIKey,
        user_performing_action: DATestUser | None = None,
    ) -> None:
        api_key_response = requests.delete(
            f"{API_SERVER_URL}/admin/api-key/{api_key.api_key_id}",
            headers=(
                user_performing_action.headers
                if user_performing_action
                else GENERAL_HEADERS
            ),
        )
        api_key_response.raise_for_status()

    @staticmethod
    def get_all(
        user_performing_action: DATestUser | None = None,
    ) -> list[DATestAPIKey]:
        api_key_response = requests.get(
            f"{API_SERVER_URL}/admin/api-key",
            headers=(
                user_performing_action.headers
                if user_performing_action
                else GENERAL_HEADERS
            ),
        )
        api_key_response.raise_for_status()
        return [DATestAPIKey(**api_key) for api_key in api_key_response.json()]

    @staticmethod
    def verify(
        api_key: DATestAPIKey,
        verify_deleted: bool = False,
        user_performing_action: DATestUser | None = None,
    ) -> None:
        retrieved_keys = APIKeyManager.get_all(
            user_performing_action=user_performing_action
        )
        for key in retrieved_keys:
            if key.api_key_id == api_key.api_key_id:
                if verify_deleted:
                    raise ValueError("API Key found when it should have been deleted")
                if (
                    key.api_key_name == api_key.api_key_name
                    and key.api_key_role == api_key.api_key_role
                ):
                    return

        if not verify_deleted:
            raise Exception("API Key not found")
