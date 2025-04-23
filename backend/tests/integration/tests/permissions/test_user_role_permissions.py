"""
This file tests the ability of different user types to set the role of other users.
"""

import os

import pytest
from requests.exceptions import HTTPError

from onyx.db.models import UserRole
from tests.integration.common_utils.managers.user import DATestUser
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.managers.user_group import UserGroupManager


@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="Curator and user group tests are enterprise only",
)
def test_user_role_setting_permissions(reset: None) -> None:
    # Creating an admin user (first user created is automatically an admin)
    admin_user: DATestUser = UserManager.create(name="admin_user")
    assert UserManager.is_role(admin_user, UserRole.ADMIN)

    # Creating a basic user
    basic_user: DATestUser = UserManager.create(name="basic_user")
    assert UserManager.is_role(basic_user, UserRole.BASIC)

    # Creating a curator
    curator: DATestUser = UserManager.create(name="curator")
    assert UserManager.is_role(curator, UserRole.BASIC)

    # Creating a curator without adding to a group should not work
    with pytest.raises(HTTPError):
        UserManager.set_role(
            user_to_set=curator,
            target_role=UserRole.CURATOR,
            user_performing_action=admin_user,
        )

    global_curator: DATestUser = UserManager.create(name="global_curator")
    assert UserManager.is_role(global_curator, UserRole.BASIC)

    # Setting the role of a global curator should not work for a basic user
    with pytest.raises(HTTPError):
        UserManager.set_role(
            user_to_set=global_curator,
            target_role=UserRole.GLOBAL_CURATOR,
            user_performing_action=basic_user,
        )

    # Setting the role of a global curator should work for an admin user
    UserManager.set_role(
        user_to_set=global_curator,
        target_role=UserRole.GLOBAL_CURATOR,
        user_performing_action=admin_user,
    )
    assert UserManager.is_role(global_curator, UserRole.GLOBAL_CURATOR)

    # Setting the role of a global curator should not work for an invalid curator
    with pytest.raises(HTTPError):
        UserManager.set_role(
            user_to_set=global_curator,
            target_role=UserRole.BASIC,
            user_performing_action=global_curator,
        )
    assert UserManager.is_role(global_curator, UserRole.GLOBAL_CURATOR)

    # Creating a user group
    user_group_1 = UserGroupManager.create(
        name="user_group_1",
        user_ids=[],
        cc_pair_ids=[],
        user_performing_action=admin_user,
    )
    UserGroupManager.wait_for_sync(
        user_groups_to_check=[user_group_1], user_performing_action=admin_user
    )

    # This should fail because the curator is not in the user group
    with pytest.raises(HTTPError):
        UserGroupManager.set_curator_status(
            test_user_group=user_group_1,
            user_to_set_as_curator=curator,
            user_performing_action=admin_user,
        )

    # Adding the curator to the user group
    user_group_1.user_ids = [curator.id]
    UserGroupManager.edit(user_group=user_group_1, user_performing_action=admin_user)
    UserGroupManager.wait_for_sync(
        user_groups_to_check=[user_group_1], user_performing_action=admin_user
    )

    # This should work because the curator is in the user group
    UserGroupManager.set_curator_status(
        test_user_group=user_group_1,
        user_to_set_as_curator=curator,
        user_performing_action=admin_user,
    )
