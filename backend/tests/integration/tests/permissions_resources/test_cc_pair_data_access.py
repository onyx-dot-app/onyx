"""Data-access groups of cc-pairs: the cc-pair and group-side APIs, the create
request, and the legacy group PATCH.

Search visibility under the query-time filter is covered in
tests/external_dependency_unit/document_index/test_cc_pair_access_filter.py,
because these tests cannot turn on the enforce flag.
"""

import os
from collections.abc import Generator

import httpx
import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import InputType
from onyx.db.enums import AccessType, ConnectorManageRole
from tests.integration.common_utils.constants import (
    API_SERVER_URL,
    MOCK_CONNECTOR_SERVER_HOST,
    MOCK_CONNECTOR_SERVER_PORT,
)
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.user_group import UserGroupManager
from tests.integration.common_utils.test_models import (
    DATestCCPair,
    DATestUser,
    DATestUserGroup,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="User groups are enterprise only",
)

_FORBIDDEN = 403
_BAD_REQUEST = 400
_MISSING_GROUP_ID = 999_999_999
_FEATURE_NOT_AVAILABLE = 402


def _private_pair(
    admin: DATestUser, groups: list[int], data_access: list[int] | None = None
) -> DATestCCPair:
    return CCPairManager.create_from_scratch(
        access_type=AccessType.PRIVATE,
        groups=groups,
        data_access=data_access,
        user_performing_action=admin,
    )


def test_create_data_access_defaults_to_manage_groups(
    permission_admin_user: DATestUser,
    scoped_managed_group: DATestUserGroup,
    scoped_other_group: DATestUserGroup,
) -> None:
    admin = permission_admin_user
    default_pair = _private_pair(admin, groups=[scoped_managed_group.id])
    assert CCPairManager.get_data_access_group_ids(default_pair.id, admin) == {
        scoped_managed_group.id
    }

    explicit_pair = _private_pair(
        admin, groups=[scoped_managed_group.id], data_access=[scoped_other_group.id]
    )
    assert CCPairManager.get_data_access_group_ids(explicit_pair.id, admin) == {
        scoped_other_group.id
    }

    with pytest.raises(httpx.HTTPStatusError) as error:
        CCPairManager.create_from_scratch(
            access_type=AccessType.PUBLIC,
            data_access=[scoped_other_group.id],
            user_performing_action=admin,
        )
    assert error.value.response.status_code == _BAD_REQUEST

    with pytest.raises(httpx.HTTPStatusError) as error:
        _private_pair(admin, groups=[], data_access=[_MISSING_GROUP_ID])
    assert error.value.response.status_code == _BAD_REQUEST


def test_scoped_manager_changes_only_groups_they_can_see(
    permission_admin_user: DATestUser,
    scoped_manager_user: DATestUser,
    scoped_managed_group: DATestUserGroup,
    scoped_other_group: DATestUserGroup,
) -> None:
    admin = permission_admin_user
    manager = scoped_manager_user
    pair = _private_pair(
        admin,
        groups=[scoped_managed_group.id],
        data_access=[scoped_managed_group.id, scoped_other_group.id],
    )

    # The manager sees only the group they manage.
    assert CCPairManager.get_data_access_group_ids(pair.id, manager) == {
        scoped_managed_group.id
    }

    # Removing everything they can see keeps the group they can't see.
    CCPairManager.set_data_access(pair.id, [], manager).raise_for_status()
    assert CCPairManager.get_data_access_group_ids(pair.id, admin) == {
        scoped_other_group.id
    }

    # They can't add a group they can't see.
    CCPairManager.set_data_access(pair.id, [], admin).raise_for_status()
    response = CCPairManager.set_data_access(pair.id, [scoped_other_group.id], manager)
    assert response.status_code == _FORBIDDEN
    assert CCPairManager.get_data_access_group_ids(pair.id, admin) == set()

    CCPairManager.set_data_access(
        pair.id, [scoped_managed_group.id], manager
    ).raise_for_status()
    assert CCPairManager.get_data_access_group_ids(pair.id, admin) == {
        scoped_managed_group.id
    }


def test_data_access_needs_editor(
    permission_admin_user: DATestUser,
    permission_basic_user: DATestUser,
    scoped_manager_user: DATestUser,
    scoped_managed_group: DATestUserGroup,
    scoped_other_group: DATestUserGroup,
) -> None:
    admin = permission_admin_user
    # Managed only by a group the manager does not manage, so not editable.
    unmanaged_pair = _private_pair(admin, groups=[scoped_other_group.id])
    for user in (scoped_manager_user, permission_basic_user):
        response = CCPairManager.set_data_access(
            unmanaged_pair.id, [scoped_managed_group.id], user
        )
        assert response.status_code == _FORBIDDEN, user.email

    # An Operator of the pair may not change its data access; an Editor may.
    pair = _private_pair(admin, groups=[], data_access=[])
    CCPairManager.set_manage_access(
        pair.id,
        {scoped_managed_group.id: ConnectorManageRole.OPERATOR},
        user_performing_action=admin,
    )
    response = CCPairManager.set_data_access(
        pair.id, [scoped_managed_group.id], scoped_manager_user
    )
    assert response.status_code == _FORBIDDEN
    CCPairManager.set_manage_access(
        pair.id,
        {scoped_managed_group.id: ConnectorManageRole.EDITOR},
        user_performing_action=admin,
    )
    CCPairManager.set_data_access(
        pair.id, [scoped_managed_group.id], scoped_manager_user
    ).raise_for_status()
    assert CCPairManager.get_data_access_group_ids(pair.id, admin) == {
        scoped_managed_group.id
    }

    public_pair = CCPairManager.create_from_scratch(user_performing_action=admin)
    response = CCPairManager.set_data_access(
        public_pair.id, [scoped_managed_group.id], admin
    )
    assert response.status_code == _BAD_REQUEST


def test_group_side_data_access(
    permission_admin_user: DATestUser,
    scoped_manager_user: DATestUser,
    scoped_managed_group: DATestUserGroup,
    scoped_other_group: DATestUserGroup,
) -> None:
    admin = permission_admin_user
    UserGroupManager.wait_for_sync(
        user_performing_action=admin,
        user_groups_to_check=[scoped_managed_group, scoped_other_group],
    )
    pair = _private_pair(admin, groups=[scoped_managed_group.id], data_access=[])

    UserGroupManager.set_data_access_cc_pairs(
        scoped_other_group, [pair.id], admin
    ).raise_for_status()
    assert CCPairManager.get_data_access_group_ids(pair.id, admin) == {
        scoped_other_group.id
    }

    # The manager can't change a group they don't manage.
    response = UserGroupManager.set_data_access_cc_pairs(
        scoped_other_group, [], scoped_manager_user
    )
    assert response.status_code == _FORBIDDEN

    # Nor attach a pair they can't edit to a group they do manage.
    unmanaged_pair = _private_pair(admin, groups=[scoped_other_group.id])
    response = UserGroupManager.set_data_access_cc_pairs(
        scoped_managed_group, [unmanaged_pair.id], scoped_manager_user
    )
    assert response.status_code == _FORBIDDEN

    UserGroupManager.set_data_access_cc_pairs(
        scoped_managed_group, [pair.id], scoped_manager_user
    ).raise_for_status()
    assert CCPairManager.get_data_access_group_ids(pair.id, admin) == {
        scoped_managed_group.id,
        scoped_other_group.id,
    }

    # A pair the manager can't edit stays when their request leaves it out.
    UserGroupManager.set_data_access_cc_pairs(
        scoped_managed_group, [pair.id, unmanaged_pair.id], admin
    ).raise_for_status()
    response = UserGroupManager.set_data_access_cc_pairs(
        scoped_managed_group, [], scoped_manager_user
    )
    response.raise_for_status()
    assert response.json()["cc_pair_ids"] == [unmanaged_pair.id]
    assert CCPairManager.get_data_access_group_ids(pair.id, admin) == {
        scoped_other_group.id
    }


def test_legacy_group_patch_writes_manage_and_data_access(
    permission_admin_user: DATestUser,
) -> None:
    admin = permission_admin_user
    pair = _private_pair(admin, groups=[])
    group = UserGroupManager.create(cc_pair_ids=[pair.id], user_performing_action=admin)
    assert CCPairManager.get_data_access_group_ids(pair.id, admin) == {group.id}

    UserGroupManager.wait_for_sync(
        user_performing_action=admin, user_groups_to_check=[group]
    )
    group.cc_pair_ids = []
    UserGroupManager.edit(group, user_performing_action=admin)
    assert CCPairManager.get_data_access_group_ids(pair.id, admin) == set()


# --- SYNC_RESTRICTED --------------------------------------------------------


def _set_group_restrictions(enabled: bool | None, admin: DATestUser) -> None:
    client.put(
        f"{API_SERVER_URL}/admin/security",
        json={"allow_connector_group_restrictions": enabled},
        headers=admin.headers,
    ).raise_for_status()


@pytest.fixture
def group_restrictions_on(
    permission_admin_user: DATestUser,
) -> Generator[None, None, None]:
    _set_group_restrictions(True, permission_admin_user)
    yield
    _set_group_restrictions(None, permission_admin_user)


def _restricted_pair(admin: DATestUser, data_access: list[int]) -> DATestCCPair:
    return CCPairManager.create_from_scratch(
        source=DocumentSource.MOCK_CONNECTOR,
        input_type=InputType.POLL,
        connector_specific_config={
            "mock_server_host": MOCK_CONNECTOR_SERVER_HOST,
            "mock_server_port": MOCK_CONNECTOR_SERVER_PORT,
        },
        access_type=AccessType.SYNC_RESTRICTED,
        data_access=data_access,
        user_performing_action=admin,
    )


def test_restricted_create_needs_workspace_toggle_and_a_group(
    permission_admin_user: DATestUser,
    scoped_managed_group: DATestUserGroup,
) -> None:
    admin = permission_admin_user
    with pytest.raises(httpx.HTTPStatusError) as error:
        _restricted_pair(admin, data_access=[scoped_managed_group.id])
    assert error.value.response.status_code == _FEATURE_NOT_AVAILABLE

    _set_group_restrictions(True, admin)
    try:
        # With no data-access group the connector would be visible to nobody.
        with pytest.raises(httpx.HTTPStatusError) as error:
            _restricted_pair(admin, data_access=[])
        assert error.value.response.status_code == _BAD_REQUEST

        pair = _restricted_pair(admin, data_access=[scoped_managed_group.id])
        assert CCPairManager.get_data_access_group_ids(pair.id, admin) == {
            scoped_managed_group.id
        }
    finally:
        _set_group_restrictions(None, admin)


@pytest.mark.usefixtures("group_restrictions_on")
def test_restricted_data_access_keeps_a_group(
    permission_admin_user: DATestUser,
    scoped_managed_group: DATestUserGroup,
    scoped_other_group: DATestUserGroup,
) -> None:
    admin = permission_admin_user
    # A syncing group refuses group-side writes.
    UserGroupManager.wait_for_sync(
        user_performing_action=admin,
        user_groups_to_check=[scoped_managed_group, scoped_other_group],
    )
    pair = _restricted_pair(admin, data_access=[scoped_managed_group.id])

    CCPairManager.set_data_access(
        pair.id, [scoped_managed_group.id, scoped_other_group.id], admin
    ).raise_for_status()
    CCPairManager.set_data_access(
        pair.id, [scoped_other_group.id], admin
    ).raise_for_status()

    response = CCPairManager.set_data_access(pair.id, [], admin)
    assert response.status_code == _BAD_REQUEST
    response = UserGroupManager.set_data_access_cc_pairs(scoped_other_group, [], admin)
    assert response.status_code == _BAD_REQUEST
    assert CCPairManager.get_data_access_group_ids(pair.id, admin) == {
        scoped_other_group.id
    }

    # The group side can add a restricted pair too. A fresh group has no other
    # pairs, so the PUT's full list is just this one.
    new_group = UserGroupManager.create(admin, name="restricted-group-side")
    UserGroupManager.wait_for_sync(
        user_performing_action=admin, user_groups_to_check=[new_group]
    )
    UserGroupManager.set_data_access_cc_pairs(
        new_group, [pair.id], admin
    ).raise_for_status()
    assert CCPairManager.get_data_access_group_ids(pair.id, admin) == {
        scoped_other_group.id,
        new_group.id,
    }
