from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, create_autospec, patch

import pytest
from pydantic import ValidationError

from ee.onyx.external_permissions.dealcloud import group_sync
from ee.onyx.external_permissions.dealcloud.access import (
    entry_type_group_id,
    reads_every_entry,
)
from ee.onyx.external_permissions.dealcloud.capability_checks import (
    build_dealcloud_doc_permission_sync_checks,
    build_dealcloud_group_sync_checks,
)
from ee.onyx.external_permissions.dealcloud.group_sync import entry_type_groups
from ee.onyx.external_permissions.utils import instance_key
from onyx.configs.app_configs import PERMISSION_SYNC_TIMEOUT
from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
)
from onyx.connectors.dealcloud.connector import DealCloudConnector
from onyx.connectors.dealcloud.models import (
    DealCloudEntryType,
    DealCloudUser,
    DealCloudUserGroup,
    DealCloudUserGroupRef,
)
from onyx.connectors.dealcloud.source_operations import DealCloudSourceOperations
from onyx.connectors.models import HierarchyNode, SlimDocument

_BASE_URL = "https://example.dealcloud.com"
_INSTANCE = instance_key(_BASE_URL)
_NO_DEADLINE: float = float("inf")
_COMPANY = DealCloudEntryType(
    id=2014, api_name="Company", plural_name="Companies", entry_list_type=1
)
_DEAL = DealCloudEntryType(
    id=2020, api_name="Deal", plural_name="Deals", entry_list_type=1
)
_READ_ALL: dict[str, Any] = {
    "readData": "All",
    "entryLevelCapabilities": {"read": {"allEntryListsAllowed": True}},
}
_GROUPS: list[dict[str, Any]] = [
    {"id": 1, "name": "Deal Team", "users": [10, 11, 13], **_READ_ALL},
    {"id": 2, "name": "Partners", "users": [11, 12], **_READ_ALL},
    # Reads only some objects, in a shape the API docs do not describe.
    {
        "id": 3,
        "name": "Fundraising",
        "users": [14],
        "readData": "All",
        "entryLevelCapabilities": {"read": {"allEntryListsAllowed": False}},
    },
    {"id": 4, "name": "Assigned Only", "users": [15], "readData": "Assigned"},
    {"id": 5, "name": "No Access", "users": [16], "readData": "None"},
]
_USERS: list[DealCloudUser] = [
    DealCloudUser(id=10, email="Ada@Example.com "),
    DealCloudUser(id=11, email="ben@example.com"),
    DealCloudUser(id=12, email="cy@example.com"),
    # 13 is in a group but is not an active user, so the listing leaves it out.
    DealCloudUser(id=14, email="fundraiser@example.com"),
    DealCloudUser(id=15, email="assigned@example.com"),
    DealCloudUser(id=16, email="none@example.com"),
]


def _ops(groups: list[dict[str, Any]] | None = None) -> MagicMock:
    by_id = {
        group["id"]: DealCloudUserGroup.model_validate(group)
        for group in (_GROUPS if groups is None else groups)
    }
    ops = create_autospec(DealCloudSourceOperations, instance=True)
    ops.list_entry_types.return_value = [_COMPANY, _DEAL]
    ops.list_active_users.return_value = _USERS
    ops.list_user_groups.return_value = [
        DealCloudUserGroupRef(id=group_id) for group_id in by_id
    ]
    ops.get_user_group.side_effect = lambda group_id: by_id[group_id]
    return ops


def _connector(ops: MagicMock) -> DealCloudConnector:
    connector = DealCloudConnector(base_url=_BASE_URL)
    connector._ops = ops
    return connector


def _context(ops: MagicMock) -> CapabilityCheckContext:
    return CapabilityCheckContext(
        source=DocumentSource.DEALCLOUD,
        credential_json={},
        connector_specific_config={"base_url": _BASE_URL},
        source_operations=ops,
    )


def _check(checks: list[CapabilityCheck], check_id: str) -> CapabilityCheck:
    return next(check for check in checks if check.check_id == check_id)


@pytest.mark.parametrize(
    "group, expected",
    [
        (_GROUPS[0], True),
        (_GROUPS[2], False),
        (_GROUPS[3], False),
        (_GROUPS[4], False),
        ({"id": 9, "name": "Bare", "users": []}, False),
    ],
    ids=["read all", "some objects", "assigned only", "none", "nothing stated"],
)
def test_only_a_group_dealcloud_says_reads_everything_is_a_reader(
    group: dict[str, Any], expected: bool
) -> None:
    assert reads_every_entry(DealCloudUserGroup.model_validate(group)) is expected


@pytest.mark.parametrize(
    "members",
    [
        {"users": [10, 11]},
        {"users": [{"id": 10}, {"id": 11}]},
        {"memberIds": [10, 11]},
        {"users": [], "memberIds": [{"id": 10}, {"id": 11}]},
    ],
    ids=["user ids", "user objects", "member ids", "empty users with members"],
)
def test_a_groups_members_are_read_in_each_shape_dealcloud_sends(
    members: dict[str, Any],
) -> None:
    group = DealCloudUserGroup.model_validate({"id": 1, "name": "Deal Team", **members})

    assert group.users == [10, 11]


def test_a_member_without_an_id_fails_the_read() -> None:
    """Leaving the member out would hide entries from a user without an error."""
    with pytest.raises(ValidationError):
        DealCloudUserGroup.model_validate(
            {"id": 1, "name": "Deal Team", "users": [{"name": "Ada"}]}
        )


def test_each_object_group_holds_the_active_members_of_the_read_all_groups() -> None:
    groups = list(entry_type_groups(_connector(_ops()), _NO_DEADLINE))

    assert [group.id for group in groups] == [
        entry_type_group_id(_INSTANCE, 2014),
        entry_type_group_id(_INSTANCE, 2020),
    ]
    for group in groups:
        assert group.user_emails == [
            "ada@example.com",
            "ben@example.com",
            "cy@example.com",
        ]
        assert group.gives_anyone_access is False


def test_the_permission_walk_names_each_objects_group() -> None:
    ops = _ops()
    ops.list_entry_ids.side_effect = lambda entry_type_id: (
        [7] if entry_type_id == 2014 else []
    )
    connector = _connector(ops)

    with patch(
        "onyx.connectors.dealcloud.access.global_version.is_ee_version", lambda: True
    ):
        items = [
            item
            for batch in connector.retrieve_all_slim_docs_perm_sync()
            for item in batch
        ]

    company_node, company_entry, deal_node = items
    assert isinstance(company_node, HierarchyNode)
    assert isinstance(company_entry, SlimDocument)
    assert isinstance(deal_node, HierarchyNode)
    for item, entry_type_id in (
        (company_node, 2014),
        (company_entry, 2014),
        (deal_node, 2020),
    ):
        access = item.external_access
        assert access is not None
        assert access.external_user_group_ids == {
            entry_type_group_id(_INSTANCE, entry_type_id)
        }
        assert access.external_user_emails == set()
        assert access.is_public is False


def test_a_group_sync_past_its_deadline_reads_nothing_and_yields_nothing() -> None:
    ops = _ops()

    with pytest.raises(RuntimeError, match="timeout"):
        list(entry_type_groups(_connector(ops), deadline=0.0))
    ops.list_active_users.assert_not_called()


def test_the_group_sync_gives_its_reads_one_deadline() -> None:
    connector = _connector(_ops())
    clock = SimpleNamespace(monotonic=lambda: 1_000.0)

    with (
        patch.object(group_sync, "dealcloud_connector", return_value=connector),
        patch.object(group_sync, "time", clock),
        patch.object(group_sync, "entry_type_groups", return_value=iter(())) as groups,
    ):
        list(group_sync.dealcloud_group_sync("tenant", MagicMock()))

    groups.assert_called_once_with(connector, 1_000.0 + PERMISSION_SYNC_TIMEOUT)


def test_a_deadline_that_passes_between_group_reads_stops_the_sync() -> None:
    ops = _ops()
    clock = SimpleNamespace(now=1_000.0)
    read_group = ops.get_user_group.side_effect

    def slow_read(group_id: int) -> DealCloudUserGroup:
        clock.now += 10.0
        return read_group(group_id)

    ops.get_user_group.side_effect = slow_read

    with (
        patch.object(group_sync, "time", SimpleNamespace(monotonic=lambda: clock.now)),
        pytest.raises(RuntimeError, match="timeout"),
    ):
        list(entry_type_groups(_connector(ops), deadline=1_015.0))
    # Two reads of 10 seconds pass the deadline, so the other groups are not read.
    assert ops.get_user_group.call_count == 2


def test_the_groups_check_counts_the_groups_onyx_leaves_out_without_naming_them() -> (
    None
):
    check = _check(
        build_dealcloud_doc_permission_sync_checks(), "dealcloud_user_groups"
    )

    output = check.run(_context(_ops()))

    assert output is not None
    (advisory,) = output.advisories
    assert advisory.message.startswith("2 DealCloud user groups read only part")
    assert "Fundraising" not in advisory.message
    assert "Assigned Only" not in advisory.message


def test_the_groups_check_passes_clean_when_every_group_reads_all_or_nothing() -> None:
    check = _check(build_dealcloud_group_sync_checks(), "dealcloud_user_groups")

    assert check.run(_context(_ops([_GROUPS[0], _GROUPS[4]]))) is None


def test_revoking_the_last_read_all_group_passes_validation_and_empties_the_groups() -> (
    None
):
    """A failed check would stop the sync and leave the earlier members in
    the groups."""
    ops = _ops([_GROUPS[2], _GROUPS[3]])
    check = _check(build_dealcloud_group_sync_checks(), "dealcloud_user_groups")

    output = check.run(_context(ops))

    assert output is not None
    assert "no Onyx user will see" in output.advisories[0].message
    groups = list(entry_type_groups(_connector(ops), _NO_DEADLINE))
    assert len(groups) == 2
    assert all(group.user_emails == [] for group in groups)


def test_the_emails_check_warns_when_no_user_has_an_email() -> None:
    check = _check(build_dealcloud_group_sync_checks(), "dealcloud_user_emails")
    ops = _ops()
    ops.list_active_users.return_value = [DealCloudUser(id=10)]

    output = check.run(_context(ops))

    assert output is not None
    assert "no active user with an email" in output.advisories[0].message
    assert all(
        group.user_emails == []
        for group in entry_type_groups(_connector(ops), _NO_DEADLINE)
    )
