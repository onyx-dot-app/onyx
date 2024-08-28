from typing import cast

import requests

from ee.danswer.server.user_group.models import UserGroup
from ee.danswer.server.user_group.models import UserGroupCreate
from tests.integration.common_utils.constants import API_SERVER_URL


class UserGroupClient:
    @staticmethod
    def create_user_group(user_group_creation_request: UserGroupCreate) -> int:
        response = requests.post(
            f"{API_SERVER_URL}/manage/admin/user-group",
            json=user_group_creation_request.dict(),
        )
        response.raise_for_status()
        return cast(int, response.json()["id"])

    @staticmethod
    def fetch_user_groups() -> list[UserGroup]:
        response = requests.get(f"{API_SERVER_URL}/manage/admin/user-group")
        response.raise_for_status()
        return [UserGroup(**ug) for ug in response.json()]
