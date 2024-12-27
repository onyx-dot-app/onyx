from copy import deepcopy
from urllib.parse import urlencode
from uuid import uuid4

import pytest
import requests
from requests import HTTPError

from onyx.auth.schemas import UserRole
from onyx.auth.schemas import UserStatus
from onyx.server.documents.models import PaginatedReturn
from onyx.server.models import FullUserSnapshot
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.constants import GENERAL_HEADERS
from tests.integration.common_utils.test_models import DATestUser

DOMAIN = "test.com"
DEFAULT_PASSWORD = "TestPassword123!"


def build_email(name: str) -> str:
    return f"{name}@test.com"


class UserManager:
    @staticmethod
    def create(
        name: str | None = None,
        email: str | None = None,
        is_first_user: bool = False,
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

        role = UserRole.ADMIN if is_first_user else UserRole.BASIC

        test_user = DATestUser(
            id=response.json()["id"],
            email=email,
            password=password,
            headers=deepcopy(GENERAL_HEADERS),
            role=role,
            status=UserStatus.LIVE,
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
    def verify_role(
        user_to_verify: DATestUser,
        target_role: UserRole | None = None,
    ) -> bool:
        if target_role is None:
            target_role = user_to_verify.role

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
        user_performing_action: DATestUser | None = None,
    ) -> DATestUser:
        if user_performing_action is None:
            user_performing_action = user_to_set
        response = requests.patch(
            url=f"{API_SERVER_URL}/manage/set-user-role",
            json={"user_email": user_to_set.email, "new_role": target_role.value},
            headers=user_performing_action.headers,
        )
        response.raise_for_status()
        user_to_set.role = target_role
        return user_to_set

    @staticmethod
    def verify_status(
        user_to_verify: DATestUser, target_status: UserStatus | None = None
    ) -> bool:
        if target_status is None:
            target_status = user_to_verify.status
        response = requests.get(
            url=f"{API_SERVER_URL}/me",
            headers=user_to_verify.headers,
        )
        response.raise_for_status()

        is_active = response.json().get("is_active", None)
        if is_active is None:
            raise KeyError("The 'is_active' field is not found in the user's info")
        return target_status == UserStatus("live" if is_active else "deactivated")

    @staticmethod
    def set_status(
        user_to_set: DATestUser,
        target_status: UserStatus,
        user_performing_action: DATestUser | None = None,
    ) -> DATestUser:
        if user_performing_action is None:
            user_performing_action = user_to_set
        if target_status == UserStatus.LIVE:
            url_substring = "activate"
        elif target_status == UserStatus.DEACTIVATED:
            url_substring = "deactivate"
        response = requests.patch(
            url=f"{API_SERVER_URL}/manage/admin/{url_substring}-user",
            json={"user_email": user_to_set.email},
            headers=user_performing_action.headers,
        )
        response.raise_for_status()
        user_to_set.status = target_status
        return user_to_set

    @staticmethod
    def create_test_users(
        user_name_prefix: str,
        count: int,
        role: UserRole = UserRole.BASIC,
        status: UserStatus | None = None,
        user_performing_action: DATestUser | None = None,
    ) -> list[DATestUser]:
        users_list = []
        for i in range(1, count + 1):
            user = UserManager.create(name=f"{user_name_prefix}_{i}")
            if role != UserRole.BASIC:
                user = UserManager.set_role(user, role, user_performing_action)
            if status:
                user = UserManager.set_status(user, status, user_performing_action)

            if status == UserStatus.DEACTIVATED:
                with pytest.raises(HTTPError):
                    UserManager.verify_role(user)
                with pytest.raises(HTTPError):
                    UserManager.verify_status(user)
            else:
                assert UserManager.verify_role(user)
                assert UserManager.verify_status(user)
            users_list.append(user)
        return users_list

    @staticmethod
    def get_user_page(
        page: int = 1,
        page_size: int = 10,
        search_query: str | None = None,
        role_filter: list[str] | None = None,
        status_filter: UserStatus | None = None,
        user_performing_action: DATestUser | None = None,
    ) -> PaginatedReturn[FullUserSnapshot]:
        query_params = {
            "page": page,
            "page_size": page_size,
            "q": search_query if search_query else None,
            "roles": role_filter if role_filter else None,
            "status": status_filter.value if status_filter else None,
        }
        # Remove None values
        query_params = {
            key: value for key, value in query_params.items() if value is not None
        }

        response = requests.get(
            url=f"{API_SERVER_URL}/manage/users/accepted?{urlencode(query_params, doseq=True)}",
            headers=user_performing_action.headers
            if user_performing_action
            else GENERAL_HEADERS,
        )
        response.raise_for_status()

        data = response.json()
        paginated_result = PaginatedReturn(
            items=[FullUserSnapshot(**user) for user in data["items"]],
            total_items=data["total_items"],
        )
        assert len(paginated_result.items) == page_size
        return paginated_result
