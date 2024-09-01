"""
This file tests the ability of different user types to set the role of other users.
"""
from danswer.db.models import UserRole
from tests.integration.common_utils.user import TestUser
from tests.integration.common_utils.user import UserManager
from tests.integration.common_utils.user_group import UserGroupManager


def test_user_role_setting_permissions(reset: None) -> None:
    # Creating an admin user (first user created is automatically an admin)
    admin_user: TestUser = UserManager.create(name="admin_user")
    assert UserManager.verify_role(admin_user, UserRole.ADMIN)

    # Creating a basic user
    basic_user: TestUser = UserManager.create(name="basic_user")
    assert UserManager.verify_role(basic_user, UserRole.BASIC)

    # Creating a curator
    curator: TestUser = UserManager.create(name="curator")
    assert UserManager.verify_role(curator, UserRole.BASIC)

    # Creating a curator without adding to a group should not work
    assert not UserManager.set_role(
        user_to_set=curator,
        target_role=UserRole.CURATOR,
        user_to_perform_action=admin_user,
    )

    global_curator: TestUser = UserManager.create(name="global_curator")
    assert UserManager.verify_role(global_curator, UserRole.BASIC)

    # Setting the role of a global curator should not work for a basic user
    assert not UserManager.set_role(
        user_to_set=global_curator,
        target_role=UserRole.GLOBAL_CURATOR,
        user_to_perform_action=basic_user,
    )
    assert UserManager.set_role(
        user_to_set=global_curator,
        target_role=UserRole.GLOBAL_CURATOR,
        user_to_perform_action=admin_user,
    )
    assert UserManager.verify_role(global_curator, UserRole.GLOBAL_CURATOR)

    # Setting the role of a global curator should not work for an invalid curator
    assert not UserManager.set_role(
        user_to_set=global_curator,
        target_role=UserRole.BASIC,
        user_to_perform_action=global_curator,
    )
    assert UserManager.verify_role(global_curator, UserRole.GLOBAL_CURATOR)

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
    assert not UserGroupManager.set_user_to_curator(
        test_user_group=user_group_1,
        user_to_set_as_curator=curator,
        user_performing_action=admin_user,
    )

    # Adding the curator to the user group
    user_group_1.user_ids = [curator.id]
    assert UserGroupManager.edit(user_group_1, user_performing_action=admin_user)
    UserGroupManager.wait_for_sync(
        user_groups_to_check=[user_group_1], user_performing_action=admin_user
    )

    # This should work because the curator is in the user group
    assert UserGroupManager.set_user_to_curator(
        test_user_group=user_group_1,
        user_to_set_as_curator=curator,
        user_performing_action=admin_user,
    )
