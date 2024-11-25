from datetime import datetime
from datetime import timedelta

import jwt
import requests

from danswer.server.manage.models import AllUsersResponse
from danswer.server.models import FullUserSnapshot
from danswer.server.models import InvitedUserSnapshot
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.constants import GENERAL_HEADERS
from tests.integration.common_utils.test_models import DATestUser


def generate_auth_token() -> str:
    payload = {
        "iss": "control_plane",
        "exp": datetime.utcnow() + timedelta(minutes=5),
        "iat": datetime.utcnow(),
        "scope": "tenant:create",
    }
    token = jwt.encode(payload, "", algorithm="HS256")
    return token


class TenantManager:
    @staticmethod
    def create(
        tenant_id: str | None = None,
        initial_admin_email: str | None = None,
    ) -> dict[str, str]:
        body = {
            "tenant_id": tenant_id,
            "initial_admin_email": initial_admin_email,
        }

        token = generate_auth_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "X-API-KEY": "",
            "Content-Type": "application/json",
        }

        response = requests.post(
            url=f"{API_SERVER_URL}/tenants/create",
            json=body,
            headers=headers,
        )

        response.raise_for_status()

        return response.json()

    @staticmethod
    def get_all_users(
        user_performing_action: DATestUser | None = None,
    ) -> AllUsersResponse:
        response = requests.get(
            url=f"{API_SERVER_URL}/manage/users",
            headers=user_performing_action.headers
            if user_performing_action
            else GENERAL_HEADERS,
        )
        response.raise_for_status()

        data = response.json()
        return AllUsersResponse(
            accepted=[FullUserSnapshot(**user) for user in data["accepted"]],
            invited=[InvitedUserSnapshot(**user) for user in data["invited"]],
            accepted_pages=data["accepted_pages"],
            invited_pages=data["invited_pages"],
        )

    @staticmethod
    def verify_user_in_tenant(
        user: DATestUser, user_performing_action: DATestUser | None = None
    ) -> None:
        all_users = TenantManager.get_all_users(user_performing_action)
        for accepted_user in all_users.accepted:
            if accepted_user.email == user.email and accepted_user.id == user.id:
                return
        raise ValueError(f"User {user.email} not found in tenant")
