import requests

from onyx.db.enums import AccountType
from onyx.server.models import FullUserSnapshot
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestUser


def _verify_user_pagination(
    users: list[DATestUser],
    user_performing_action: DATestUser,
    page_size: int = 5,
    search_query: str | None = None,
    is_active_filter: bool | None = None,
) -> None:
    """Walk every page and verify:

    - ``total_items`` matches the expected cohort on every page.
    - Each page has exactly the right length (accounting for a partial
      last page — the previous implementation asserted ``page_size`` on
      every page, which hid this bug behind cohort sizes that happened to
      be multiples of ``page_size``).
    - No user is returned on more than one page (set-based comparison
      would have masked cross-page duplicates).
    - Union across pages matches the expected cohort exactly.
    """
    total = len(users)
    assert total > 0, "helper requires at least one expected user"
    num_pages = (total + page_size - 1) // page_size

    retrieved_items: list[FullUserSnapshot] = []
    for page_num in range(num_pages):
        page = UserManager.get_user_page(
            page_num=page_num,
            page_size=page_size,
            search_query=search_query,
            is_active_filter=is_active_filter,
            user_performing_action=user_performing_action,
        )
        expected_on_page = min(page_size, total - page_num * page_size)
        assert page.total_items == total
        assert len(page.items) == expected_on_page, (
            f"page {page_num} returned {len(page.items)} items, "
            f"expected {expected_on_page} (total={total}, page_size={page_size})"
        )
        retrieved_items.extend(page.items)

    retrieved_emails = [u.email for u in retrieved_items]
    assert len(retrieved_emails) == len(
        set(retrieved_emails)
    ), f"pagination returned duplicate emails across pages: {retrieved_emails}"
    assert set(retrieved_emails) == {u.email for u in users}


def test_user_pagination(reset: None) -> None:  # noqa: ARG001
    """Verify pagination and search/active filters on the accepted-users
    endpoint. Cohort sizes are deliberately non-multiples of ``page_size``
    so the partial-last-page branch is exercised."""
    user_performing_action: DATestUser = UserManager.create(
        name="admin_performing_action"
    )

    # 9 more admins → 10 admin users total (including the performing user).
    admin_users: list[DATestUser] = UserManager.create_test_users(
        user_name_prefix="admin",
        count=9,
        as_admin=True,
        user_performing_action=user_performing_action,
    )
    admin_users.append(user_performing_action)

    basic_users: list[DATestUser] = UserManager.create_test_users(
        user_name_prefix="basic",
        count=7,
        user_performing_action=user_performing_action,
    )

    inactive_users: list[DATestUser] = UserManager.create_test_users(
        user_name_prefix="inactive",
        count=13,
        is_active=False,
        user_performing_action=user_performing_action,
    )

    searchable_users: list[DATestUser] = UserManager.create_test_users(
        user_name_prefix="search_user",
        count=10,
        user_performing_action=user_performing_action,
    )

    all_users: list[DATestUser] = (
        admin_users + basic_users + inactive_users + searchable_users
    )
    active_users: list[DATestUser] = admin_users + basic_users + searchable_users
    for user in all_users:
        assert UserManager.is_status(user, user.is_active)

    # Full pagination — 40 users, page_size 5 → 8 full pages.
    _verify_user_pagination(
        users=all_users,
        user_performing_action=user_performing_action,
    )

    # Active filter — 27 users, page_size 5 → partial last page of 2.
    _verify_user_pagination(
        users=active_users,
        is_active_filter=True,
        user_performing_action=user_performing_action,
    )

    # Inactive filter — 13 users, page_size 5 → partial last page of 3.
    _verify_user_pagination(
        users=inactive_users,
        is_active_filter=False,
        user_performing_action=user_performing_action,
    )

    # Search query (substring match on email).
    _verify_user_pagination(
        users=searchable_users,
        search_query="search_user",
        user_performing_action=user_performing_action,
    )

    # Combining status and search filters.
    _verify_user_pagination(
        users=inactive_users,
        is_active_filter=False,
        search_query="inactive",
        user_performing_action=user_performing_action,
    )


def test_user_pagination_edge_cases(reset: None) -> None:  # noqa: ARG001
    """Boundary behaviour of /manage/users/accepted: oversized page, out-of-range
    page_num, empty search result, and case-insensitive substring search."""
    admin: DATestUser = UserManager.create(name="admin_edge")

    # 3 deterministic-prefix users to exercise search; admin itself also counts.
    UserManager.create_test_users(
        user_name_prefix="uniq_search",
        count=3,
        user_performing_action=admin,
    )
    # accepted users now: admin + 3 search users = 4 total.

    # page_size greater than total → single page returns everything.
    oversized = UserManager.get_user_page(
        page_num=0,
        page_size=100,
        user_performing_action=admin,
    )
    assert oversized.total_items == 4
    assert len(oversized.items) == 4

    # page_num past the last page → empty items, total_items stays accurate.
    out_of_range = UserManager.get_user_page(
        page_num=50,
        page_size=5,
        user_performing_action=admin,
    )
    assert out_of_range.total_items == 4
    assert out_of_range.items == []

    # Search with no matches → zero total, zero items.
    no_match = UserManager.get_user_page(
        page_num=0,
        page_size=10,
        search_query="zzz_no_such_user_exists",
        user_performing_action=admin,
    )
    assert no_match.total_items == 0
    assert no_match.items == []

    # Case-insensitive substring match — users were created with lowercase prefix;
    # uppercase query should still match via the backend's ilike('%q%') filter
    # (onyx/db/users.py:_get_accepted_user_where_clause).
    case_insensitive = UserManager.get_user_page(
        page_num=0,
        page_size=10,
        search_query="UNIQ_SEARCH",
        user_performing_action=admin,
    )
    assert case_insensitive.total_items == 3
    assert len(case_insensitive.items) == 3
    assert all("uniq_search" in u.email for u in case_insensitive.items)


def test_user_pagination_account_types_filter(reset: None) -> None:  # noqa: ARG001
    """The ``account_types`` filter on /manage/users/accepted narrows results to
    users whose ``account_type`` is in the supplied list, while omitting the
    filter returns the full accepted-user set.

    This guards against the silent filter removal that shipped in the
    UserRole-cleanup PR: an endpoint tagged PUBLIC_API_TAGS must not drop
    filter params without a replacement.
    """
    admin: DATestUser = UserManager.create(name="admin_account_types")

    bot_email = "bot_filter@example.com"
    UserManager.seed_non_web_user(AccountType.BOT, bot_email)
    # EXT_PERM_USER is excluded by default from accepted-user listings, so
    # seeding one would not show up — BOT is the only non-STANDARD account
    # type that does surface in this endpoint.

    # No filter → all accepted users are returned (admin + bot).
    unfiltered = UserManager.get_user_page(
        page_num=0,
        page_size=100,
        user_performing_action=admin,
    )
    assert unfiltered.total_items >= 2
    returned_emails = {u.email for u in unfiltered.items}
    assert admin.email in returned_emails
    assert bot_email in returned_emails

    # Filter to BOT only → just the seeded bot.
    bots_only = UserManager.get_user_page(
        page_num=0,
        page_size=100,
        account_types=[AccountType.BOT],
        user_performing_action=admin,
    )
    assert bots_only.total_items == 1
    assert [u.email for u in bots_only.items] == [bot_email]
    assert all(u.account_type == AccountType.BOT for u in bots_only.items)

    # Filter to STANDARD only → admin is present, bot is absent.
    standard_only = UserManager.get_user_page(
        page_num=0,
        page_size=100,
        account_types=[AccountType.STANDARD],
        user_performing_action=admin,
    )
    standard_emails = {u.email for u in standard_only.items}
    assert admin.email in standard_emails
    assert bot_email not in standard_emails
    assert all(u.account_type == AccountType.STANDARD for u in standard_only.items)


def test_user_pagination_rejects_removed_roles_param(
    reset: None,  # noqa: ARG001
) -> None:
    """Callers still passing the removed ``roles`` filter must receive a clear
    400 pointing at ``account_types`` — silent ignore would return unfiltered
    results for any external integration that hasn't migrated."""
    admin: DATestUser = UserManager.create(name="admin_roles_reject")

    response = requests.get(
        url=f"{API_SERVER_URL}/manage/users/accepted",
        params={"roles": "admin"},
        headers=admin.headers,
    )
    assert response.status_code == 400
    body = response.json()
    assert body["error_code"] == "INVALID_INPUT"
    assert "account_types" in body["detail"]
