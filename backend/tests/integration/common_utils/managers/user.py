from copy import deepcopy
from urllib.parse import urlencode
from uuid import uuid4

import pytest
import requests
from requests import HTTPError

from onyx.auth.schemas import UserRole
from onyx.configs.constants import FASTAPI_USERS_AUTH_COOKIE_NAME
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
            is_active=True,
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
        session_cookie = cookies.get(FASTAPI_USERS_AUTH_COOKIE_NAME)

        if not session_cookie:
            raise Exception("Failed to login")

        print(f"Logged in as {test_user.email}")

        # Set cookies in the headers
        test_user.headers["Cookie"] = f"fastapiusersauth={session_cookie}; "
        test_user.cookies = {"fastapiusersauth": session_cookie}
        return test_user

    @staticmethod
    def is_role(
        user_to_verify: DATestUser,
        target_role: UserRole,
    ) -> bool:
        response = requests.get(
            url=f"{API_SERVER_URL}/me",
            headers=user_to_verify.headers,
            cookies=user_to_verify.cookies,
        )

        if user_to_verify.is_active is False:
            with pytest.raises(HTTPError):
                response.raise_for_status()
            return user_to_verify.role == target_role
        else:
            response.raise_for_status()

        role_from_response = response.json().get("role", None)

        if role_from_response is None:
            return user_to_verify.role == target_role

        return target_role == UserRole(role_from_response)

    @staticmethod
    def set_role(
        user_to_set: DATestUser,
        target_role: UserRole,
        user_performing_action: DATestUser,
    ) -> DATestUser:
        response = requests.patch(
            url=f"{API_SERVER_URL}/manage/set-user-role",
            json={"user_email": user_to_set.email, "new_role": target_role.value},
            headers=user_performing_action.headers,
        )
        response.raise_for_status()

        new_user_updated_role = DATestUser(
            id=user_to_set.id,
            email=user_to_set.email,
            password=user_to_set.password,
            headers=user_to_set.headers,
            role=target_role,
            is_active=user_to_set.is_active,
        )
        return new_user_updated_role

    # TODO: Add a way to check invited status
    @staticmethod
    def is_status(user_to_verify: DATestUser, target_status: bool) -> bool:
        response = requests.get(
            url=f"{API_SERVER_URL}/me",
            headers=user_to_verify.headers,
        )

        if target_status is False:
            with pytest.raises(HTTPError):
                response.raise_for_status()
        else:
            response.raise_for_status()

        is_active = response.json().get("is_active", None)
        if is_active is None:
            return user_to_verify.is_active == target_status
        return target_status == is_active

    @staticmethod
    def set_status(
        user_to_set: DATestUser,
        target_status: bool,
        user_performing_action: DATestUser,
    ) -> DATestUser:
        url_substring: str
        if target_status is True:
            url_substring = "activate"
        elif target_status is False:
            url_substring = "deactivate"
        response = requests.patch(
            url=f"{API_SERVER_URL}/manage/admin/{url_substring}-user",
            json={"user_email": user_to_set.email},
            headers=user_performing_action.headers,
        )
        response.raise_for_status()

        new_user_updated_status = DATestUser(
            id=user_to_set.id,
            email=user_to_set.email,
            password=user_to_set.password,
            headers=user_to_set.headers,
            role=user_to_set.role,
            is_active=target_status,
        )
        return new_user_updated_status

    @staticmethod
    def create_test_users(
        user_performing_action: DATestUser,
        user_name_prefix: str,
        count: int,
        role: UserRole = UserRole.BASIC,
        is_active: bool | None = None,
    ) -> list[DATestUser]:
        users_list = []
        for i in range(1, count + 1):
            user = UserManager.create(name=f"{user_name_prefix}_{i}")
            if role != UserRole.BASIC:
                user = UserManager.set_role(user, role, user_performing_action)
            if is_active is not None:
                user = UserManager.set_status(user, is_active, user_performing_action)
            users_list.append(user)
        return users_list

    @staticmethod
    def get_user_page(
        page_num: int = 0,
        page_size: int = 10,
        search_query: str | None = None,
        role_filter: list[UserRole] | None = None,
        is_active_filter: bool | None = None,
        user_performing_action: DATestUser | None = None,
    ) -> PaginatedReturn[FullUserSnapshot]:
        query_params: dict[str, str | list[str] | int] = {
            "page_num": page_num,
            "page_size": page_size,
        }
        if search_query:
            query_params["q"] = search_query
        if role_filter:
            query_params["roles"] = [role.value for role in role_filter]
        if is_active_filter is not None:
            query_params["is_active"] = is_active_filter

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
        return paginated_result
