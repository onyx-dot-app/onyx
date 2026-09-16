import json
from pathlib import Path

import pytest

from ee.onyx.external_permissions.onedrive.permission_mapper import (
    map_onedrive_permissions,
)
from onyx.access.utils import build_ext_group_name_for_onyx
from onyx.configs.constants import DocumentSource
from onyx.connectors.onedrive.models import OneDrivePermission

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "tenant_spike.json"


@pytest.fixture
def permission_shapes() -> dict[str, list[OneDrivePermission]]:
    fixture = json.loads(FIXTURE_PATH.read_text())
    return {
        name: [
            OneDrivePermission.model_validate(permission)
            for permission in payload["value"]
        ]
        for name, payload in fixture["permission_shapes"].items()
    }


def test_fixture_user_and_group_permissions_are_conservative(
    permission_shapes: dict[str, list[OneDrivePermission]],
) -> None:
    direct = map_onedrive_permissions(
        permission_shapes["direct"], "<owner-email>", False, False
    )
    restricted = map_onedrive_permissions(
        permission_shapes["restricted"], "<owner-email>", False, False
    )
    group = map_onedrive_permissions(
        permission_shapes["visible_group"], "<owner-email>", False, False
    )

    assert direct.external_user_emails == {"<owner-email>", "<primary-user-email>"}
    assert restricted.external_user_emails == {
        "<owner-email>",
        "<alternate-user-email>",
    }
    assert group.external_user_group_ids == {"<visible-group-id>"}
    assert not group.is_public


def test_fixture_inheritance_and_permission_mutations_remain_restricted(
    permission_shapes: dict[str, list[OneDrivePermission]],
) -> None:
    cases = {
        "inherited": {"<owner-email>", "<primary-user-email>"},
        "move_destination_after": {"<owner-email>", "<alternate-user-email>"},
        "remove_share_after": {"<owner-email>"},
        "restore_inheritance_after": {"<owner-email>", "<primary-user-email>"},
    }

    for shape, expected_users in cases.items():
        access = map_onedrive_permissions(
            permission_shapes[shape], "<owner-email>", False, False
        )
        assert access.external_user_emails == expected_users
        assert not access.is_public


def test_fixture_hidden_group_stays_restricted_to_its_group(
    permission_shapes: dict[str, list[OneDrivePermission]],
) -> None:
    access = map_onedrive_permissions(
        permission_shapes["hidden_group"], "<owner-email>", False, False
    )

    assert access.external_user_emails == {"<owner-email>"}
    assert access.external_user_group_ids == {"<hidden-group-id>"}
    assert not access.is_public


def test_indexing_prefixes_fixture_group_once() -> None:
    permissions = [
        OneDrivePermission.model_validate(permission)
        for permission in json.loads(FIXTURE_PATH.read_text())["permission_shapes"][
            "visible_group"
        ]["value"]
    ]

    access = map_onedrive_permissions(permissions, "<owner-email>", False, True)

    assert access.external_user_group_ids == {
        build_ext_group_name_for_onyx("<visible-group-id>", DocumentSource.ONEDRIVE)
    }


def test_fixture_link_policy_does_not_widen_organization_links(
    permission_shapes: dict[str, list[OneDrivePermission]],
) -> None:
    anonymous = map_onedrive_permissions(
        permission_shapes["anonymous_link"], "<owner-email>", False, False
    )
    organization_private = map_onedrive_permissions(
        permission_shapes["organization_link"], "<owner-email>", False, False
    )
    organization_public = map_onedrive_permissions(
        permission_shapes["organization_link"], "<owner-email>", True, False
    )

    assert anonymous.is_public
    assert not organization_private.is_public
    assert organization_public.is_public


def test_unresolved_grants_are_dropped_without_widening() -> None:
    permissions = [
        OneDrivePermission.model_validate(
            {
                "roles": ["read"],
                "grantedToV2": {"user": {"id": "unresolved-user"}},
            }
        ),
        OneDrivePermission.model_validate(
            {
                "roles": ["read"],
                "grantedToV2": {"group": {"displayName": "unresolved-group"}},
            }
        ),
    ]

    access = map_onedrive_permissions(permissions, "owner@example.com", False, False)

    assert access.external_user_emails == {"owner@example.com"}
    assert access.external_user_group_ids == set()
    assert not access.is_public
