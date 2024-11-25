from copy import deepcopy
from urllib.parse import urlencode
from uuid import uuid4

import requests

from danswer.db.models import UserRole
from danswer.server.manage.models import AllUsersResponse
from danswer.server.models import FullUserSnapshot
from danswer.server.models import InvitedUserSnapshot
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.constants import GENERAL_HEADERS
from tests.integration.common_utils.test_models import DATestUser


DOMAIN = "test.com"
DEFAULT_PASSWORD = "test"


def build_email(name: str) -> str:
    return f"{name}@test.com"


class UserManager:
    @staticmethod
    def create(
        name: str | None = None,
        email: str | None = None,
    ) -> DATestUser:
        if name is None:
            name = f"test{str(uuid4())}"

        if email is None:
            email = build_email(name)

        password = DEFAULT_PASSWORD

        body = {
            "email": email,
            "username": email,
            "password": password,
        }
        response = requests.post(
            url=f"{API_SERVER_URL}/auth/register",
            json=body,
            headers=GENERAL_HEADERS,
        )
        response.raise_for_status()

        test_user = DATestUser(
            id=response.json()["id"],
            email=email,
            password=password,
            headers=deepcopy(GENERAL_HEADERS),
        )
        print(f"Created user {test_user.email}")

        return UserManager.login_as_user(test_user)

    @staticmethod
    def login_as_user(test_user: DATestUser) -> DATestUser:
        data = urlencode(
            {
                "username": test_user.email,
                "password": test_user.password,
            }
        )
        headers = test_user.headers.copy()
        headers["Content-Type"] = "application/x-www-form-urlencoded"

        response = requests.post(
            url=f"{API_SERVER_URL}/auth/login",
            data=data,
            headers=headers,
        )

        response.raise_for_status()

        cookies = response.cookies.get_dict()
        session_cookie = cookies.get("fastapiusersauth")

        if not session_cookie:
            raise Exception("Failed to login")

        print(f"Logged in as {test_user.email}")

        # Set cookies in the headers
        test_user.headers["Cookie"] = f"fastapiusersauth={session_cookie}; "
        return test_user

    @staticmethod
    def verify_role(user_to_verify: DATestUser, target_role: UserRole) -> bool:
        response = requests.get(
            url=f"{API_SERVER_URL}/me",
            headers=user_to_verify.headers,
        )
        response.raise_for_status()
        return target_role == UserRole(response.json().get("role", ""))

    @staticmethod
    def set_role(
        user_to_set: DATestUser,
        target_role: UserRole,
        user_to_perform_action: DATestUser | None = None,
    ) -> None:
        if user_to_perform_action is None:
            user_to_perform_action = user_to_set
        response = requests.patch(
            url=f"{API_SERVER_URL}/manage/set-user-role",
            json={"user_email": user_to_set.email, "new_role": target_role.value},
            headers=user_to_perform_action.headers,
        )
        response.raise_for_status()

    @staticmethod
    def verify(
        user: DATestUser, user_to_perform_action: DATestUser | None = None
    ) -> None:
        if user_to_perform_action is None:
            user_to_perform_action = user
        response = requests.get(
            url=f"{API_SERVER_URL}/manage/users",
            headers=user_to_perform_action.headers
            if user_to_perform_action
            else GENERAL_HEADERS,
        )
        response.raise_for_status()

        data = response.json()
        all_users = AllUsersResponse(
            accepted=[FullUserSnapshot(**user) for user in data["accepted"]],
            invited=[InvitedUserSnapshot(**user) for user in data["invited"]],
            accepted_pages=data["accepted_pages"],
            invited_pages=data["invited_pages"],
        )
        for accepted_user in all_users.accepted:
            if accepted_user.email == user.email and accepted_user.id == user.id:
                return
        raise ValueError(f"User {user.email} not found")
