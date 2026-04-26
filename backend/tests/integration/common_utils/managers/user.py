from copy import deepcopy
from typing import Any
from urllib.parse import urlencode
from uuid import uuid4

import pytest
import requests
from requests import HTTPError

from onyx.configs.constants import ANONYMOUS_USER_EMAIL
from onyx.configs.constants import ANONYMOUS_USER_UUID
from onyx.configs.constants import FASTAPI_USERS_AUTH_COOKIE_NAME
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import AccountType
from onyx.db.enums import Permission
from onyx.db.users import add_slack_user_if_not_exists
from onyx.db.users import batch_add_ext_perm_user_if_not_exists
from onyx.server.documents.models import PaginatedReturn
from onyx.server.manage.models import UserInfo
from onyx.server.models import FullUserSnapshot
from onyx.server.models import InvitedUserSnapshot
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.constants import GENERAL_HEADERS
from tests.integration.common_utils.test_models import DATestUser

DOMAIN = "example.com"
DEFAULT_PASSWORD = "TestPassword123!"


def build_email(name: str) -> str:
    return f"{name}@example.com"


def _is_admin_from_me_response(me_json: dict[str, Any]) -> bool:
    """Determine admin-ness from the /me endpoint response.

    Admin is now driven by membership in the Admin default group, which
    surfaces as `FULL_ADMIN_PANEL_ACCESS` in `effective_permissions`.
    """
    permissions: list[str] = me_json.get("effective_permissions", [])
    return Permission.FULL_ADMIN_PANEL_ACCESS.value in permissions


class UserManager:
    @staticmethod
    def get_anonymous_user() -> DATestUser:
        """Get a DATestUser representing the anonymous user.

        Anonymous users are real users in the database with account_type=ANONYMOUS.
        They don't have login cookies — requests are made with GENERAL_HEADERS.
        The anonymous_user_enabled setting must be True for these requests to work.
        """
        return DATestUser(
            id=ANONYMOUS_USER_UUID,
            email=ANONYMOUS_USER_EMAIL,
            password="",
            headers=GENERAL_HEADERS,
            is_admin=False,
            is_active=True,
        )

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
            # `login_as_user` will refresh this from /me after login
            is_admin=False,
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

        # Get user info from /me endpoint
        me_response = requests.get(
            url=f"{API_SERVER_URL}/me",
            headers=test_user.headers,
            cookies=test_user.cookies,
        )
        me_response.raise_for_status()
        me_response_json = me_response.json()
        test_user.id = me_response_json["id"]
        test_user.is_admin = _is_admin_from_me_response(me_response_json)

        return test_user

    @staticmethod
    def get_permissions(user: DATestUser) -> list[str]:
        response = requests.get(
            url=f"{API_SERVER_URL}/me/permissions",
            headers=user.headers,
        )
        response.raise_for_status()
        return response.json()

    @staticmethod
    def is_admin(user_to_verify: DATestUser) -> bool:
        """Check whether the user currently holds admin privileges."""
        response = requests.get(
            url=f"{API_SERVER_URL}/me",
            headers=user_to_verify.headers,
            cookies=user_to_verify.cookies,
        )

        if user_to_verify.is_active is False:
            with pytest.raises(HTTPError):
                response.raise_for_status()
            return user_to_verify.is_admin
        else:
            response.raise_for_status()

        return _is_admin_from_me_response(response.json())

    @staticmethod
    def promote_to_admin(
        user_to_promote: DATestUser,
        user_performing_action: DATestUser,
    ) -> DATestUser:
        """Promote a user to admin by adding them to the Admin default group."""
        groups_response = requests.get(
            url=f"{API_SERVER_URL}/manage/admin/user-group?include_default=true",
            headers=user_performing_action.headers,
        )
        groups_response.raise_for_status()
        admin_group = next(
            (
                g
                for g in groups_response.json()
                if g.get("is_default") is True and g.get("name") == "Admin"
            ),
            None,
        )
        if admin_group is None:
            raise RuntimeError("Admin default group not found")

        response = requests.post(
            url=f"{API_SERVER_URL}/manage/admin/user-group/{admin_group['id']}/add-users",
            json={"user_ids": [user_to_promote.id]},
            headers=user_performing_action.headers,
        )
        response.raise_for_status()

        return DATestUser(
            id=user_to_promote.id,
            email=user_to_promote.email,
            password=user_to_promote.password,
            headers=user_to_promote.headers,
            is_admin=True,
            is_active=user_to_promote.is_active,
            cookies=user_to_promote.cookies,
        )

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
            url=f"{API_SERVER_URL}/manage/admin/{url_substring}-user",  # ty: ignore[possibly-unresolved-reference]
            json={"user_email": user_to_set.email},
            headers=user_performing_action.headers,
        )
        response.raise_for_status()

        return DATestUser(
            id=user_to_set.id,
            email=user_to_set.email,
            password=user_to_set.password,
            headers=user_to_set.headers,
            is_admin=user_to_set.is_admin,
            is_active=target_status,
            cookies=user_to_set.cookies,
        )

    @staticmethod
    def create_test_users(
        user_performing_action: DATestUser,
        user_name_prefix: str,
        count: int,
        as_admin: bool = False,
        is_active: bool | None = None,
    ) -> list[DATestUser]:
        users_list = []
        for i in range(1, count + 1):
            user = UserManager.create(name=f"{user_name_prefix}_{i}")
            if as_admin:
                user = UserManager.promote_to_admin(user, user_performing_action)
            if is_active is not None:
                user = UserManager.set_status(user, is_active, user_performing_action)
            users_list.append(user)
        return users_list

    @staticmethod
    def get_user_page(
        user_performing_action: DATestUser,
        page_num: int = 0,
        page_size: int = 10,
        search_query: str | None = None,
        is_active_filter: bool | None = None,
        account_types: list[AccountType] | None = None,
    ) -> PaginatedReturn[FullUserSnapshot]:
        query_params: dict[str, str | list[str] | int] = {
            "page_num": page_num,
            "page_size": page_size,
        }
        if search_query:
            query_params["q"] = search_query
        if is_active_filter is not None:
            query_params["is_active"] = is_active_filter
        if account_types:
            query_params["account_types"] = [at.value for at in account_types]

        response = requests.get(
            url=f"{API_SERVER_URL}/manage/users/accepted?{urlencode(query_params, doseq=True)}",
            headers=user_performing_action.headers,
        )
        response.raise_for_status()

        data = response.json()
        paginated_result = PaginatedReturn(
            items=[FullUserSnapshot(**user) for user in data["items"]],
            total_items=data["total_items"],
        )
        return paginated_result

    @staticmethod
    def seed_non_web_user(account_type: AccountType, email: str) -> None:
        """Seed a BOT or EXT_PERM_USER account directly via the internal DB
        helpers. Emails are lowercased to match the ``User`` model's
        normalization validator — assertions that reuse the seeded email will
        otherwise miss the DB row."""
        email = email.lower()
        with get_session_with_current_tenant() as db_session:
            if account_type == AccountType.BOT:
                add_slack_user_if_not_exists(db_session, email=email)
            elif account_type == AccountType.EXT_PERM_USER:
                batch_add_ext_perm_user_if_not_exists(db_session, emails=[email])
            else:
                raise ValueError(f"Unsupported seed account_type: {account_type}")

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
