from copy import deepcopy
from urllib.parse import urlencode
from uuid import uuid4

import pytest
import requests
from requests import HTTPError

from onyx.auth.schemas import UserRole
from onyx.configs.constants import FASTAPI_USERS_AUTH_COOKIE_NAME
from onyx.server.documents.models import PaginatedReturn
from onyx.server.manage.models import UserInfo
from onyx.server.models import FullUserSnapshot
from onyx.server.models import InvitedUserSnapshot
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
            # fill as basic for now, the `login_as_user` call will
            # fill it in correctly
            role=UserRole.BASIC,
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

        # Set cookies in the headers
        test_user.headers["Cookie"] = f"fastapiusersauth={session_cookie}; "
        test_user.cookies = {"fastapiusersauth": session_cookie}

        # Get user role from /me endpoint
        me_response = requests.get(
            url=f"{API_SERVER_URL}/me",
            headers=test_user.headers,
            cookies=test_user.cookies,
        )
        me_response.raise_for_status()
        me_response_json = me_response.json()
        test_user.id = me_response_json["id"]
        role = UserRole(me_response_json["role"])
        test_user.role = role

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
        explicit_override: bool = False,
    ) -> DATestUser:
        response = requests.patch(
            url=f"{API_SERVER_URL}/manage/set-user-role",
            json={
                "user_email": user_to_set.email,
                "new_role": target_role.value,
                "explicit_override": explicit_override,
            },
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
            headers=(
                user_performing_action.headers
                if user_performing_action
                else GENERAL_HEADERS
            ),
        )
        response.raise_for_status()

        data = response.json()
        paginated_result = PaginatedReturn(
            items=[FullUserSnapshot(**user) for user in data["items"]],
            total_items=data["total_items"],
        )
        return paginated_result

    @staticmethod
    def invite_user(
        user_to_invite_email: str, user_performing_action: DATestUser
    ) -> None:
        """Invite a user by email to join the organization.

        Args:
            user_to_invite_email: Email of the user to invite
            user_performing_action: User with admin permissions performing the invitation
        """
        response = requests.put(
            url=f"{API_SERVER_URL}/manage/admin/users",
            headers=user_performing_action.headers,
            json={"emails": [user_to_invite_email]},
        )
        response.raise_for_status()

    @staticmethod
    def accept_invitation(tenant_id: str, user_performing_action: DATestUser) -> None:
        """Accept an invitation to join the organization.

        Args:
            tenant_id: ID of the tenant/organization to accept invitation for
            user_performing_action: User accepting the invitation
        """
        response = requests.post(
            url=f"{API_SERVER_URL}/tenants/users/invite/accept",
            headers=user_performing_action.headers,
            json={"tenant_id": tenant_id},
        )
        response.raise_for_status()

    @staticmethod
    def get_invited_users(
        user_performing_action: DATestUser,
    ) -> list[InvitedUserSnapshot]:
        """Get a list of all invited users.

        Args:
            user_performing_action: User with admin permissions performing the action

        Returns:
            List of invited user snapshots
        """
        response = requests.get(
            url=f"{API_SERVER_URL}/manage/users/invited",
            headers=user_performing_action.headers,
        )
        response.raise_for_status()

        return [InvitedUserSnapshot(**user) for user in response.json()]

    @staticmethod
    def get_user_info(user_performing_action: DATestUser) -> UserInfo:
        """Get user info for the current user.

        Args:
            user_performing_action: User performing the action
        """
        response = requests.get(
            url=f"{API_SERVER_URL}/me",
            headers=user_performing_action.headers,
        )
        response.raise_for_status()
        return UserInfo(**response.json())
