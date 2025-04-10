"""
This file tests the permissions for creating and editing personas for different user roles:
- Basic users can create personas and edit their own
- Curators can edit personas that belong exclusively to groups they curate
- Admins can edit all personas
"""

import os

import pytest
from requests.exceptions import HTTPError

from tests.integration.common_utils.managers.persona import PersonaManager
from tests.integration.common_utils.managers.user import DATestUser
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.managers.user_group import UserGroupManager


@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="Curator and user group tests are enterprise only",
)
def test_persona_permissions(reset: None) -> None:
    # Creating an admin user (first user created is automatically an admin)
    admin_user: DATestUser = UserManager.create(name="admin_user")

    # Creating a curator user
    curator: DATestUser = UserManager.create(name="curator")

    # Creating a basic user
    basic_user: DATestUser = UserManager.create(name="basic_user")

    # Creating user groups
    user_group_1 = UserGroupManager.create(
        name="curated_user_group",
        user_ids=[curator.id],
        cc_pair_ids=[],
        user_performing_action=admin_user,
    )
    UserGroupManager.wait_for_sync(
        user_groups_to_check=[user_group_1], user_performing_action=admin_user
    )
    # Setting the user as a curator for the user group
    UserGroupManager.set_curator_status(
        test_user_group=user_group_1,
        user_to_set_as_curator=curator,
        user_performing_action=admin_user,
    )

    # Creating another user group that the user is not a curator of
    user_group_2 = UserGroupManager.create(
        name="uncurated_user_group",
        user_ids=[curator.id],
        cc_pair_ids=[],
        user_performing_action=admin_user,
    )
    UserGroupManager.wait_for_sync(
        user_groups_to_check=[user_group_2], user_performing_action=admin_user
    )

    """Test that any user can create a persona"""
    # Basic user creates a persona
    basic_user_persona = PersonaManager.create(
        name="basic_user_persona",
        description="A persona created by basic user",
        is_public=False,
        groups=[],
        users=[admin_user.id],
        user_performing_action=basic_user,
    )
    PersonaManager.verify(basic_user_persona, user_performing_action=basic_user)

    # Curator creates a persona
    curator_persona = PersonaManager.create(
        name="curator_persona",
        description="A persona created by curator",
        is_public=False,
        groups=[],
        user_performing_action=curator,
    )
    PersonaManager.verify(curator_persona, user_performing_action=curator)

    # Admin creates personas for different groups
    admin_persona_group_1 = PersonaManager.create(
        name="admin_persona_group_1",
        description="A persona for group 1",
        is_public=False,
        groups=[user_group_1.id],
        user_performing_action=admin_user,
    )
    admin_persona_group_2 = PersonaManager.create(
        name="admin_persona_group_2",
        description="A persona for group 2",
        is_public=False,
        groups=[user_group_2.id],
        user_performing_action=admin_user,
    )
    admin_persona_both_groups = PersonaManager.create(
        name="admin_persona_both_groups",
        description="A persona for both groups",
        is_public=False,
        groups=[user_group_1.id, user_group_2.id],
        user_performing_action=admin_user,
    )

    """Test that users can edit their own personas"""
    # Basic user can edit their own persona
    PersonaManager.edit(
        persona=basic_user_persona,
        description="Updated description by basic user",
        user_performing_action=basic_user,
    )
    PersonaManager.verify(basic_user_persona, user_performing_action=basic_user)

    # Basic user cannot edit other's personas
    with pytest.raises(HTTPError):
        PersonaManager.edit(
            persona=curator_persona,
            description="Invalid edit by basic user",
            user_performing_action=basic_user,
        )

    """Test curator permissions"""
    # Curator can edit personas that belong exclusively to groups they curate
    PersonaManager.edit(
        persona=admin_persona_group_1,
        description="Updated by curator",
        user_performing_action=curator,
    )
    PersonaManager.verify(admin_persona_group_1, user_performing_action=curator)

    # Curator cannot edit personas in groups they don't curate
    with pytest.raises(HTTPError):
        PersonaManager.edit(
            persona=admin_persona_group_2,
            description="Invalid edit by curator",
            user_performing_action=curator,
        )

    # Curator cannot edit personas that belong to multiple groups, even if they curate one
    with pytest.raises(HTTPError):
        PersonaManager.edit(
            persona=admin_persona_both_groups,
            description="Invalid edit by curator",
            user_performing_action=curator,
        )

    """Test admin permissions"""
    # Admin can edit any persona

    # the persona was shared with the admin user on creation
    # this edit call will simulate having the same user in the list twice.
    # The server side should dedupe and handle this correctly (prior bug)
    PersonaManager.edit(
        persona=basic_user_persona,
        description="Updated by admin 2",
        users=[admin_user.id, admin_user.id],
        user_performing_action=admin_user,
    )
    PersonaManager.verify(basic_user_persona, user_performing_action=admin_user)

    PersonaManager.edit(
        persona=curator_persona,
        description="Updated by admin",
        user_performing_action=admin_user,
    )
    PersonaManager.verify(curator_persona, user_performing_action=admin_user)

    PersonaManager.edit(
        persona=admin_persona_group_1,
        description="Updated by admin",
        user_performing_action=admin_user,
    )
    PersonaManager.verify(admin_persona_group_1, user_performing_action=admin_user)

    PersonaManager.edit(
        persona=admin_persona_group_2,
        description="Updated by admin",
        user_performing_action=admin_user,
    )
    PersonaManager.verify(admin_persona_group_2, user_performing_action=admin_user)

    PersonaManager.edit(
        persona=admin_persona_both_groups,
        description="Updated by admin",
        user_performing_action=admin_user,
    )
    PersonaManager.verify(admin_persona_both_groups, user_performing_action=admin_user)
