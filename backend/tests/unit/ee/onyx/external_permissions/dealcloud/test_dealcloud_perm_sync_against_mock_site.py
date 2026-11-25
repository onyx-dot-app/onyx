from collections.abc import Iterator
from typing import Any
from unittest.mock import patch

import pytest

from ee.onyx.connectors.perm_sync_valid import validate_dealcloud_perm_sync
from ee.onyx.external_permissions.dealcloud.access import (
    entry_type_group_id,
)
from ee.onyx.external_permissions.dealcloud.group_sync import entry_type_groups
from ee.onyx.external_permissions.utils import instance_key
from onyx.connectors.dealcloud import source_operations
from onyx.connectors.exceptions import (
    InsufficientPermissionsError,
)
from onyx.connectors.models import HierarchyNode, SlimDocument
from tests.unit.onyx.connectors.dealcloud.dealcloud_mock_site import (
    SITE_URL,
    MockSite,
    serve,
)
from tests.unit.onyx.connectors.dealcloud.test_dealcloud_against_mock_site import (
    COMPANY_ID,
    DEAL_ID,
    index,
    seeded_site,
    site_connector,
)

_INSTANCE = instance_key(SITE_URL)
_READ_ALL: dict[str, Any] = {
    "readData": "All",
    "entryLevelCapabilities": {"read": {"allEntryListsAllowed": True}},
}


def _group(group_id: int, name: str, users: list[int], **read: Any) -> dict[str, Any]:
    return {"id": group_id, "name": name, "users": users, **read}


@pytest.fixture
def site() -> Iterator[MockSite]:
    mock_site = seeded_site()
    mock_site.users = {
        10: ("Ada@Example.com", True),
        11: ("ben@example.com", True),
        12: ("left@example.com", False),
        13: ("assigned@example.com", True),
        14: (None, True),
    }
    mock_site.groups = {
        1: _group(1, "Deal Team", [10, 12, 14], **_READ_ALL),
        2: _group(2, "Partners", [11], **_READ_ALL),
        3: _group(3, "Assigned Only", [13], readData="Assigned"),
    }
    with (
        serve(mock_site),
        patch.object(source_operations, "_MIN_REQUEST_INTERVAL_SECONDS", 0.0),
    ):
        yield mock_site


def test_the_group_sync_fills_each_object_group_from_the_site(site: MockSite) -> None:
    groups = list(entry_type_groups(site_connector(), float("inf")))

    assert [group.id for group in groups] == [
        entry_type_group_id(_INSTANCE, COMPANY_ID),
        entry_type_group_id(_INSTANCE, DEAL_ID),
    ]
    # The inactive user, the user without an email and the member of the
    # group with narrower access are left out.
    assert all(
        group.user_emails == ["ada@example.com", "ben@example.com"] for group in groups
    )
    # A user management token, separate from the data token.
    assert site.count("POST", "/api/rest/v1/oauth/token") == 2
    assert site.count("GET", "/api/rest/v1/management/user/group") == 4


def test_the_group_sync_reads_members_sent_as_objects_under_member_ids(
    site: MockSite,
) -> None:
    site.groups[1] = {
        "id": 1,
        "name": "Deal Team",
        "memberIds": [{"id": 10}, {"id": 12}, {"id": 14}],
        **_READ_ALL,
    }

    groups = list(entry_type_groups(site_connector(), float("inf")))

    assert all(
        group.user_emails == ["ada@example.com", "ben@example.com"] for group in groups
    )


def test_the_first_index_gives_every_entry_and_object_its_group(
    site: MockSite,  # noqa: ARG001
) -> None:
    with patch(
        "onyx.connectors.dealcloud.access.global_version.is_ee_version", lambda: True
    ):
        documents, nodes = index(site_connector(), with_access=True)

    assert len(documents) == 10
    assert len(nodes) == 2
    for document in documents:
        entry_type_id = COMPANY_ID if f"/{COMPANY_ID}/" in document.id else DEAL_ID
        assert document.external_access is not None
        assert document.external_access.external_user_group_ids == {
            entry_type_group_id(_INSTANCE, entry_type_id)
        }
        assert document.external_access.is_public is False
    assert {
        group_id
        for node in nodes
        if node.external_access is not None
        for group_id in node.external_access.external_user_group_ids
    } == {
        entry_type_group_id(_INSTANCE, COMPANY_ID),
        entry_type_group_id(_INSTANCE, DEAL_ID),
    }


def test_a_later_index_run_leaves_access_to_the_permission_sync(
    site: MockSite,  # noqa: ARG001
) -> None:
    documents, nodes = index(site_connector())

    assert all(document.external_access is None for document in documents)
    assert all(node.external_access is None for node in nodes)


def test_the_doc_sync_walk_gives_every_live_entry_its_objects_group(
    site: MockSite,  # noqa: ARG001
) -> None:
    with patch(
        "onyx.connectors.dealcloud.access.global_version.is_ee_version", lambda: True
    ):
        items = [
            item
            for batch in site_connector().retrieve_all_slim_docs_perm_sync()
            for item in batch
        ]

    nodes = [item for item in items if isinstance(item, HierarchyNode)]
    entries = [item for item in items if isinstance(item, SlimDocument)]
    assert len(nodes) == 2
    assert len(entries) == 10
    for entry in entries:
        entry_type_id = COMPANY_ID if f"/{COMPANY_ID}/" in entry.id else DEAL_ID
        assert entry.external_access is not None
        assert entry.external_access.external_user_group_ids == {
            entry_type_group_id(_INSTANCE, entry_type_id)
        }
        assert entry.external_access.is_public is False


def test_validation_passes_then_fails_once_user_management_is_lost(
    site: MockSite,
) -> None:
    validate_dealcloud_perm_sync(site_connector())

    site.user_management_enabled = False

    with pytest.raises(InsufficientPermissionsError, match="User Management"):
        validate_dealcloud_perm_sync(site_connector())


def test_the_group_sync_fails_once_user_management_is_lost(site: MockSite) -> None:
    """Its own reads are the guard: an empty answer would empty every group."""
    site.user_management_enabled = False

    with pytest.raises(InsufficientPermissionsError, match="User Management"):
        list(entry_type_groups(site_connector(), float("inf")))


def test_revoking_the_last_read_all_group_empties_the_groups_on_the_site(
    site: MockSite,
) -> None:
    site.groups = {3: site.groups[3]}

    validate_dealcloud_perm_sync(site_connector())
    groups = list(entry_type_groups(site_connector(), float("inf")))

    assert len(groups) == 2
    assert all(group.user_emails == [] for group in groups)
