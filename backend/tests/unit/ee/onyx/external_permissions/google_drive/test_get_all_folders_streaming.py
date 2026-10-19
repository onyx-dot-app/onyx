import inspect
import time
from collections.abc import Callable, Iterator
from typing import Any
from unittest.mock import MagicMock

import pytest

from ee.onyx.external_permissions.google_drive.group_sync import (
    _drive_member_map_to_onyx_groups,
    _get_all_folders,
    _get_all_google_groups,
)
from onyx.connectors.google_drive.drive_access import (
    DriveMember,
    DriveRole,
    PrincipalType,
)
from onyx.connectors.google_drive.source_operations import (
    DriveFolderScope,
    GoogleDriveSourceOperations,
)

_ADMIN = "admin@example.com"
_ORGANIZER = "organizer@example.com"
_USERS = ["a@example.com", "b@example.com"]


def _folder(folder_id: str) -> dict[str, Any]:
    """A Drive folder payload carrying one non-inherited permission.

    No "permissionDetails" means inherited_from is None, so the permission
    survives the inherited-permission filter and the folder is kept.
    """
    permission_id = f"perm-{folder_id}"
    return {
        "id": folder_id,
        "name": folder_id,
        "permissionIds": [permission_id],
        "permissions": [
            {
                "id": permission_id,
                "type": "user",
                "emailAddress": f"{folder_id}@example.com",
            }
        ],
    }


def _member(
    email: str,
    role: DriveRole = DriveRole.ORGANIZER,
    principal_type: PrincipalType = PrincipalType.USER,
) -> DriveMember:
    return DriveMember(email=email, principal_type=principal_type, role=role)


def _make_connector(user_emails: list[str], service_account: bool = True) -> MagicMock:
    connector = MagicMock()
    connector.ops = MagicMock(spec=GoogleDriveSourceOperations)
    connector.ops.can_list_drive.return_value = True
    connector._get_all_user_emails.return_value = user_emails
    connector.is_service_account = service_account
    connector.primary_admin_email = _ADMIN
    connector.google_domain = "example.com"
    return connector


# A partition is (scope, principal, drive id).
Partition = tuple[DriveFolderScope, str, str | None]


def _partition(kwargs: dict[str, Any]) -> Partition:
    return (kwargs["scope"], kwargs["user_email"], kwargs.get("drive_id"))


def _listings(
    folders_by_partition: dict[Partition, list[dict[str, Any]]],
) -> Callable[..., Iterator[dict[str, Any]]]:
    """A folder listing that answers each partition from the given table and
    an empty page for any other partition."""

    def listing(**kwargs: Any) -> Iterator[dict[str, Any]]:
        return iter(folders_by_partition.get(_partition(kwargs), []))

    return listing


def _partitions_listed(connector: MagicMock) -> list[Partition]:
    return [
        _partition(call.kwargs)
        for call in connector.ops.list_folders_with_permissions.call_args_list
    ]


def _no_groups(_group_email: str) -> list[str]:
    return []


def test_get_all_folders_streams_without_materializing() -> None:
    """Folders must be yielded as they are found, not accumulated into a list.

    Building the full list before returning is what pinned the entire
    folder/permission graph in memory and OOM-killed the heavy worker. This
    asserts the generator emits its first folder after touching only the first
    partition, so a regression back to list-building fails here.
    """
    assert inspect.isgeneratorfunction(_get_all_folders)

    connector = _make_connector(_USERS)
    connector.ops.list_folders_with_permissions.side_effect = _listings(
        {
            (DriveFolderScope.SHARED_DRIVE, _ORGANIZER, "d1"): [
                _folder("d1-a"),
                _folder("d1-b"),
            ],
            (DriveFolderScope.OWNED, "a@example.com", None): [_folder("a1")],
            (DriveFolderScope.OWNED, "b@example.com", None): [_folder("b1")],
            (DriveFolderScope.SHARED_WITH_ME, "b@example.com", None): [_folder("ext1")],
        }
    )

    generator = _get_all_folders(
        google_drive_connector=connector,
        skip_folders_without_permissions=True,
        drive_members={"d1": [_member(_ORGANIZER)]},
        expand_group=_no_groups,
    )

    # Merely calling the function must not perform any work.
    assert connector.ops.list_folders_with_permissions.call_count == 0

    first = next(generator)

    # One folder pulled => only the first partition has been listed.
    assert first.id == "d1-a"
    assert connector.ops.list_folders_with_permissions.call_count == 1

    remaining = [folder.id for folder in generator]
    assert remaining == ["d1-b", "a1", "b1", "ext1"]


def test_service_account_lists_each_partition_once() -> None:
    """A service account must not list the whole domain once per user. Each
    shared drive is listed once as its organizer, each user's My Drive once
    as its owner, and each user's direct shares once."""
    connector = _make_connector(_USERS)
    connector.ops.list_folders_with_permissions.side_effect = _listings({})

    list(
        _get_all_folders(
            google_drive_connector=connector,
            skip_folders_without_permissions=True,
            drive_members={"d1": [_member(_ORGANIZER)], "d2": [_member(_ORGANIZER)]},
            expand_group=_no_groups,
        )
    )

    assert _partitions_listed(connector) == [
        (DriveFolderScope.SHARED_DRIVE, _ORGANIZER, "d1"),
        (DriveFolderScope.SHARED_DRIVE, _ORGANIZER, "d2"),
        (DriveFolderScope.OWNED, "a@example.com", None),
        (DriveFolderScope.OWNED, "b@example.com", None),
        (DriveFolderScope.SHARED_WITH_ME, "a@example.com", None),
        (DriveFolderScope.SHARED_WITH_ME, "b@example.com", None),
    ]


def test_organizer_comes_from_group_membership_already_synced() -> None:
    """A drive organized through a Google Group is listed as a member of that
    group, resolved through the memberships the sync read earlier rather than
    another directory call."""
    connector = _make_connector(["a@example.com"])
    connector.ops.list_folders_with_permissions.side_effect = _listings({})
    team = "team@example.com"

    list(
        _get_all_folders(
            google_drive_connector=connector,
            skip_folders_without_permissions=True,
            drive_members={"d1": [_member(team, principal_type=PrincipalType.GROUP)]},
            expand_group=lambda group: [_ORGANIZER] if group == team else [],
        )
    )

    assert _partitions_listed(connector)[0] == (
        DriveFolderScope.SHARED_DRIVE,
        _ORGANIZER,
        "d1",
    )
    connector.ops.list_group_members.assert_not_called()


def test_drive_without_impersonable_member_falls_back_to_admin() -> None:
    connector = _make_connector(["a@example.com"])
    connector.ops.list_folders_with_permissions.side_effect = _listings({})

    list(
        _get_all_folders(
            google_drive_connector=connector,
            skip_folders_without_permissions=True,
            drive_members={"d1": []},
            expand_group=_no_groups,
        )
    )

    assert _partitions_listed(connector)[0] == (
        DriveFolderScope.SHARED_DRIVE,
        _ADMIN,
        "d1",
    )


def test_drive_nobody_can_list_is_skipped() -> None:
    connector = _make_connector(["a@example.com"])
    connector.ops.can_list_drive.return_value = False
    connector.ops.list_folders_with_permissions.side_effect = _listings({})

    list(
        _get_all_folders(
            google_drive_connector=connector,
            skip_folders_without_permissions=True,
            drive_members={"d1": [_member("gone@example.com")]},
            expand_group=_no_groups,
        )
    )

    assert all(
        scope is not DriveFolderScope.SHARED_DRIVE
        for scope, _, _ in _partitions_listed(connector)
    )


def test_oauth_lists_everything_its_one_identity_sees() -> None:
    """OAuth cannot impersonate, so the partitioned walk does not apply: the
    connected user lists every folder it can see in one pass."""
    connector = _make_connector([_ADMIN], service_account=False)
    connector.ops.list_folders_with_permissions.side_effect = _listings(
        {(DriveFolderScope.ALL_DRIVES, _ADMIN, None): [_folder("f1")]}
    )

    folder_ids = [
        folder.id
        for folder in _get_all_folders(
            google_drive_connector=connector,
            skip_folders_without_permissions=True,
            drive_members={"d1": [_member(_ORGANIZER)]},
            expand_group=_no_groups,
        )
    ]

    assert folder_ids == ["f1"]
    assert _partitions_listed(connector) == [
        (DriveFolderScope.ALL_DRIVES, _ADMIN, None)
    ]
    connector.ops.can_list_drive.assert_not_called()


def test_get_all_folders_dedupes_across_partitions() -> None:
    """A folder shared directly with several users is listed in each of their
    shared-with-me passes, so the shared seen-set must still collapse
    duplicates now that folders are streamed rather than appended to a list."""
    connector = _make_connector(_USERS)
    connector.ops.list_folders_with_permissions.side_effect = _listings(
        {
            (DriveFolderScope.SHARED_WITH_ME, "a@example.com", None): [
                _folder("shared"),
                _folder("only-a"),
            ],
            (DriveFolderScope.SHARED_WITH_ME, "b@example.com", None): [
                _folder("shared"),
                _folder("only-b"),
            ],
        }
    )

    folder_ids = [
        folder.id
        for folder in _get_all_folders(
            google_drive_connector=connector,
            skip_folders_without_permissions=True,
            drive_members={},
            expand_group=_no_groups,
        )
    ]

    assert folder_ids == ["shared", "only-a", "only-b"]


def test_get_all_folders_aborts_after_too_many_user_failures() -> None:
    """Failure accounting must still abort mid-stream. With yield from, the
    per-user exception surfaces when the consumer pulls, so the guard has to
    keep working from inside the generator."""
    connector = _make_connector([f"u{i}@example.com" for i in range(4)])
    connector.ops.list_folders_with_permissions.side_effect = RuntimeError(
        "drive unavailable"
    )

    with pytest.raises(RuntimeError, match="Too many failed folder fetches"):
        list(
            _get_all_folders(
                google_drive_connector=connector,
                skip_folders_without_permissions=True,
                drive_members={},
                expand_group=_no_groups,
            )
        )


def test_get_all_folders_enforces_crawl_deadline() -> None:
    """On large domains the crawl skips almost every folder and yields nothing
    for hours, so consumer-side timeouts (checked between yields) never fire —
    the crawl must enforce its own deadline and fail the sync outright rather
    than being swallowed by the per-partition failure accounting."""

    def endless_folders(**_kwargs: Any) -> Any:
        i = 0
        while True:
            i += 1
            yield _folder(f"f{i}")

    connector = _make_connector(_USERS)
    connector.ops.list_folders_with_permissions.side_effect = endless_folders

    expired_deadline = time.monotonic() - 1
    with pytest.raises(TimeoutError, match="group sync exceeded"):
        list(
            _get_all_folders(
                google_drive_connector=connector,
                skip_folders_without_permissions=True,
                drive_members={},
                expand_group=_no_groups,
                deadline=expired_deadline,
            )
        )

    # At most the first partition was touched: the deadline ends the whole
    # sync instead of counting as a per-partition failure and moving on.
    assert connector.ops.list_folders_with_permissions.call_count <= 1


def test_group_enumeration_enforces_sync_deadline() -> None:
    """The groups phase materializes the full group list before anything
    yields, so it must check the shared sync deadline itself."""

    def endless_groups() -> Any:
        i = 0
        while True:
            i += 1
            yield f"group-{i}@example.com"

    ops = MagicMock(spec=GoogleDriveSourceOperations)
    ops.list_groups.side_effect = endless_groups
    with pytest.raises(TimeoutError, match="group sync exceeded"):
        _get_all_google_groups(ops=ops, deadline=time.monotonic() - 1)


def test_drive_members_flatten_users_and_known_groups() -> None:
    groups = list(
        _drive_member_map_to_onyx_groups(
            {
                "d1": [
                    _member("a@example.com", DriveRole.READER),
                    _member("team@example.com", principal_type=PrincipalType.GROUP),
                    _member("lost@example.com", principal_type=PrincipalType.GROUP),
                    DriveMember(
                        email=None,
                        principal_type=PrincipalType.DOMAIN,
                        role=DriveRole.READER,
                    ),
                ]
            },
            {"team@example.com": ["t1@example.com", "t2@example.com"]},
        )
    )

    (group,) = groups
    assert group.id == "d1"
    assert sorted(group.user_emails) == [
        "a@example.com",
        "t1@example.com",
        "t2@example.com",
    ]
