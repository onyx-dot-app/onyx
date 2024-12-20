from onyx.auth.schemas import UserRole
from onyx.auth.schemas import UserStatus
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestUser


def test_user_pagination(reset: None) -> None:
    all_users: list[DATestUser] = []

    # Create 10 admin users
    admin_users: list[DATestUser] = UserManager.create_test_users(
        user_name_prefix="admin", count=10, role=UserRole.ADMIN, has_first_user=True
    )
    # Set the first admin as the admin user
    admin_user: DATestUser = admin_users[0]

    # Create 20 basic users
    basic_users: list[DATestUser] = UserManager.create_test_users(
        user_name_prefix="basic", count=10, admin_user=admin_user
    )

    # Create 10 global curators
    global_curators: list[DATestUser] = UserManager.create_test_users(
        user_name_prefix="global_curator",
        count=10,
        role=UserRole.GLOBAL_CURATOR,
        admin_user=admin_user,
    )

    # Create 10 inactive admins
    inactive_admins: list[DATestUser] = UserManager.create_test_users(
        user_name_prefix="inactive_admin",
        count=10,
        role=UserRole.ADMIN,
        status=UserStatus.DEACTIVATED,
        admin_user=admin_user,
    )

    # Create 10 global curator users with an email containing "search"
    searchable_curators: list[DATestUser] = UserManager.create_test_users(
        user_name_prefix="search_curator",
        count=10,
        role=UserRole.GLOBAL_CURATOR,
        admin_user=admin_user,
    )

    # Combine all the users lists into the all_users list
    all_users = (
        admin_users
        + basic_users
        + global_curators
        + inactive_admins
        + searchable_curators
    )

    # Verify pagination
    UserManager.verify_pagination(users=all_users, user_performing_action=admin_user)

    # Verify filtering by role
    UserManager.verify_pagination(
        users=admin_users + inactive_admins,
        role_filter=[UserRole.ADMIN.value],
        user_performing_action=admin_user,
    )
    # Verify filtering by status
    UserManager.verify_pagination(
        users=inactive_admins,
        status_filter=UserStatus.DEACTIVATED,
        user_performing_action=admin_user,
    )
    # Verify filtering by search query
    UserManager.verify_pagination(
        users=searchable_curators,
        search_query="search",
        user_performing_action=admin_user,
    )

    # Verify filtering by role and status
    UserManager.verify_pagination(
        users=inactive_admins,
        role_filter=[UserRole.ADMIN.value],
        status_filter=UserStatus.DEACTIVATED,
        user_performing_action=admin_user,
    )

    # Verify filtering by role and search query
    UserManager.verify_pagination(
        users=searchable_curators,
        role_filter=[UserRole.GLOBAL_CURATOR.value],
        search_query="search",
        user_performing_action=admin_user,
    )

    # Verify filtering by role and status and search query
    UserManager.verify_pagination(
        users=inactive_admins,
        role_filter=[UserRole.ADMIN.value],
        status_filter=UserStatus.DEACTIVATED,
        search_query="inactive_ad",
        user_performing_action=admin_user,
    )
