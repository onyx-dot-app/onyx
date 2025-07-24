from onyx.auth.schemas import UserRole
from onyx.server.models import FullUserSnapshot
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestUser


# Gets a page of users from the db that match the given parameters and then
# compares that returned page to the list of users passed into the function
# to verify that the pagination and filtering works as expected.
def _verify_user_pagination(
    users: list[DATestUser],
    page_size: int = 5,
    search_query: str | None = None,
    role_filter: list[UserRole] | None = None,
    is_active_filter: bool | None = None,
    user_performing_action: DATestUser | None = None,
) -> None:
    retrieved_users: list[FullUserSnapshot] = []

    for i in range(0, len(users), page_size):
        paginated_result = UserManager.get_user_page(
            page_num=i // page_size,
            page_size=page_size,
            search_query=search_query,
            role_filter=role_filter,
            is_active_filter=is_active_filter,
            user_performing_action=user_performing_action,
        )

        # Verify that the total items is equal to the length of the users list
        assert paginated_result.total_items == len(users)
        # Verify that the number of items in the page is equal to the page size
        assert len(paginated_result.items) == page_size
        # Add the retrieved users to the list of retrieved users
        retrieved_users.extend(paginated_result.items)

    # Create a set of all the expected emails
    all_expected_emails = set([user.email for user in users])
    # Create a set of all the retrieved emails
    all_retrieved_emails = set([user.email for user in retrieved_users])

    # Verify that the set of retrieved emails is equal to the set of expected emails
    assert all_expected_emails == all_retrieved_emails


def test_user_pagination(reset: None) -> None:
    # Create an admin user to perform actions
    user_performing_action: DATestUser = UserManager.create(
        name="admin_performing_action"
    )

    # Create 9 admin users
    admin_users: list[DATestUser] = UserManager.create_test_users(
        user_name_prefix="admin",
        count=9,
        role=UserRole.ADMIN,
        user_performing_action=user_performing_action,
    )

    # Add the user_performing_action to the list of admins
    admin_users.append(user_performing_action)

    # Create 20 basic users
    basic_users: list[DATestUser] = UserManager.create_test_users(
        user_name_prefix="basic",
        count=10,
        role=UserRole.BASIC,
        user_performing_action=user_performing_action,
    )

    # Create 10 global curators
    global_curators: list[DATestUser] = UserManager.create_test_users(
        user_name_prefix="global_curator",
        count=10,
        role=UserRole.GLOBAL_CURATOR,
        user_performing_action=user_performing_action,
    )

    # Create 10 inactive admins
    inactive_admins: list[DATestUser] = UserManager.create_test_users(
        user_name_prefix="inactive_admin",
        count=10,
        role=UserRole.ADMIN,
        is_active=False,
        user_performing_action=user_performing_action,
    )

    # Create 10 global curator users with an email containing "search"
    searchable_curators: list[DATestUser] = UserManager.create_test_users(
        user_name_prefix="search_curator",
        count=10,
        role=UserRole.GLOBAL_CURATOR,
        user_performing_action=user_performing_action,
    )

    # Combine all the users lists into the all_users list
    all_users: list[DATestUser] = (
        admin_users
        + basic_users
        + global_curators
        + inactive_admins
        + searchable_curators
    )
    for user in all_users:
        # Verify that the user's role in the db matches
        # the role in the user object
        assert UserManager.is_role(user, user.role)
        # Verify that the user's status in the db matches
        # the status in the user object
        assert UserManager.is_status(user, user.is_active)

    # Verify pagination
    _verify_user_pagination(
        users=all_users,
        user_performing_action=user_performing_action,
    )

    # Verify filtering by role
    _verify_user_pagination(
        users=admin_users + inactive_admins,
        role_filter=[UserRole.ADMIN],
        user_performing_action=user_performing_action,
    )
    # Verify filtering by status
    _verify_user_pagination(
        users=inactive_admins,
        is_active_filter=False,
        user_performing_action=user_performing_action,
    )
    # Verify filtering by search query
    _verify_user_pagination(
        users=searchable_curators,
        search_query="search",
        user_performing_action=user_performing_action,
    )

    # Verify filtering by role and status
    _verify_user_pagination(
        users=inactive_admins,
        role_filter=[UserRole.ADMIN],
        is_active_filter=False,
        user_performing_action=user_performing_action,
    )

    # Verify filtering by role and search query
    _verify_user_pagination(
        users=searchable_curators,
        role_filter=[UserRole.GLOBAL_CURATOR],
        search_query="search",
        user_performing_action=user_performing_action,
    )

    # Verify filtering by role and status and search query
    _verify_user_pagination(
        users=inactive_admins,
        role_filter=[UserRole.ADMIN],
        is_active_filter=False,
        search_query="inactive_ad",
        user_performing_action=user_performing_action,
    )

    # Verify filtering by multiple roles (admin and global curator)
    _verify_user_pagination(
        users=admin_users + global_curators + inactive_admins + searchable_curators,
        role_filter=[UserRole.ADMIN, UserRole.GLOBAL_CURATOR],
        user_performing_action=user_performing_action,
    )
