"""Egnyte permission sync: folder grants become access (no deny, Viewer and
higher, administrators always), group sync builds the default groups from
user types, and the walk carries prefixed group ids on nodes and indexed
documents but bare ones on the doc sync's slim documents."""

from io import BytesIO
from unittest.mock import MagicMock

import pytest

from ee.onyx.connectors.perm_sync_valid import validate_egnyte_group_sync
from ee.onyx.external_permissions.egnyte.access import (
    custom_group_id,
    default_group_id,
    folder_access,
)
from ee.onyx.external_permissions.egnyte.group_sync import egnyte_groups
from onyx.access.utils import build_ext_group_name_for_onyx
from onyx.configs.constants import DocumentSource
from onyx.connectors.connector_runner import CheckpointOutputWrapper
from onyx.connectors.egnyte.access import EgnyteUnknownGroupError
from onyx.connectors.egnyte.connector import EgnyteCheckpoint, EgnyteConnector
from onyx.connectors.egnyte.models import (
    EgnyteDirectory,
    EgnyteFile,
    EgnyteFolder,
    EgnyteFolderPage,
    EgnyteGroup,
    EgnyteGroupMember,
    EgnyteGroupRef,
    EgnytePermissionGrant,
    EgnytePermissions,
    EgnyteUser,
    EgnyteUserInfo,
    EgnyteUserType,
)
from onyx.connectors.egnyte.source_operations import EgnyteSourceOperations
from onyx.connectors.models import Document, HierarchyNode, SlimDocument

_DOMAIN = "Acme"
_ADMINS = default_group_id(_DOMAIN, "All Administrators")
_DIRECTORY = EgnyteDirectory(
    emails_by_username={"ana": "ana@acme.com", "bo": "bo@acme.com"},
    group_ids_by_name={"Finance": "g-fin"},
)


def _grants(
    users: dict[str, str] | None = None, groups: dict[str, str] | None = None
) -> EgnytePermissions:
    return EgnytePermissions(
        users=[
            EgnytePermissionGrant(subject=subject, permission=level)
            for subject, level in (users or {}).items()
        ],
        groups=[
            EgnytePermissionGrant(subject=subject, permission=level)
            for subject, level in (groups or {}).items()
        ],
    )


def _user(name: str, user_type: EgnyteUserType, active: bool = True) -> EgnyteUser:
    return EgnyteUser(
        user_name=name, email=f"{name}@Acme.com", user_type=user_type, active=active
    )


def test_readers_are_viewer_and_higher_plus_administrators() -> None:
    access = folder_access(
        _DOMAIN,
        _grants(
            users={"ana": "Viewer", "bo": "None", "gone": "Owner"},
            groups={"Finance": "Editor", "All Power Users": "Viewer"},
        ),
        _DIRECTORY,
    )

    assert access.external_user_emails == {"ana@acme.com"}
    assert access.external_user_group_ids == {
        _ADMINS,
        custom_group_id(_DOMAIN, "g-fin"),
        default_group_id(_DOMAIN, "All Power Users"),
    }
    assert not access.is_public


def test_viewer_only_reads_the_folder() -> None:
    access = folder_access(_DOMAIN, _grants(users={"bo": "Viewer Only"}), _DIRECTORY)

    assert access.external_user_emails == {"bo@acme.com"}


def test_a_user_none_does_not_remove_a_group_grant() -> None:
    access = folder_access(
        _DOMAIN,
        _grants(users={"ana": "None"}, groups={"Finance": "Viewer"}),
        _DIRECTORY,
    )

    assert custom_group_id(_DOMAIN, "g-fin") in access.external_user_group_ids


def test_folders_without_listed_permissions_are_administrators_only() -> None:
    access = folder_access(_DOMAIN, None, _DIRECTORY)

    assert (access.external_user_emails, access.external_user_group_ids) == (
        set(),
        {_ADMINS},
    )


def test_an_unknown_group_fails_closed() -> None:
    with pytest.raises(EgnyteUnknownGroupError):
        folder_access(_DOMAIN, _grants(groups={"Ghosts": "Viewer"}), _DIRECTORY)


def test_group_sync_builds_default_groups_from_user_types() -> None:
    connector = EgnyteConnector()
    connector.load_credentials({"domain": _DOMAIN, "access_token": "test-token"})
    ops = MagicMock()
    ops.list_users.return_value = [
        _user("root", EgnyteUserType.ADMIN),
        _user("pat", EgnyteUserType.POWER),
        _user("sam", EgnyteUserType.STANDARD),
        _user("old", EgnyteUserType.STANDARD, active=False),
    ]
    ops.list_groups.return_value = [EgnyteGroupRef(id="g-fin", display_name="Finance")]
    ops.get_group.return_value = EgnyteGroup(
        id="g-fin",
        display_name="Finance",
        members=[EgnyteGroupMember(username="pat"), EgnyteGroupMember(username="old")],
    )
    connector._ops = ops

    groups = {group.id: group.user_emails for group in egnyte_groups(connector)}

    assert groups == {
        _ADMINS: ["root@acme.com"],
        default_group_id(_DOMAIN, "All Power Users"): ["pat@acme.com"],
        default_group_id(_DOMAIN, "All Standard Users"): ["sam@acme.com"],
        default_group_id(_DOMAIN, "All Standard Users and Power Users"): [
            "pat@acme.com",
            "sam@acme.com",
        ],
        custom_group_id(_DOMAIN, "g-fin"): ["pat@acme.com"],
    }


def _perm_sync_connector() -> tuple[EgnyteConnector, MagicMock]:
    """/Shared holds one file and grants Finance, as Egnyte lists it."""
    page = EgnyteFolderPage(
        folder=EgnyteFolder(name="Shared", path="/Shared", folder_id="f-shared"),
        folders=[],
        files=[
            EgnyteFile(
                name="a.txt",
                path="/Shared/a.txt",
                group_id="file-a",
                entry_id="v1",
                last_modified="Tue, 10 Nov 2026 18:00:00 GMT",
            )
        ],
    )
    ops = MagicMock()
    ops.list_users.return_value = [_user("ana", EgnyteUserType.STANDARD)]
    ops.list_groups.return_value = [EgnyteGroupRef(id="g-fin", display_name="Finance")]
    ops.list_folder_page_with_permissions.return_value = page.model_copy(
        update={"permissions": _grants(groups={"Finance": "Viewer"})}
    )
    ops.download_file.return_value = BytesIO(b"text")
    connector = EgnyteConnector(folder_path="/Shared")
    connector.load_credentials({"domain": _DOMAIN, "access_token": "test-token"})
    connector._ops = ops
    return connector, ops


def _prefixed(*group_ids: str) -> set[str]:
    return {build_ext_group_name_for_onyx(g, DocumentSource.EGNYTE) for g in group_ids}


def test_indexing_with_permissions_prefixes_documents_and_nodes() -> None:
    connector, ops = _perm_sync_connector()
    items: list[Document | HierarchyNode] = []
    checkpoint = connector.build_dummy_checkpoint()
    while checkpoint.has_more:
        for document, node, _failure, next_checkpoint in CheckpointOutputWrapper[
            EgnyteCheckpoint
        ]()(connector.load_from_checkpoint_with_perm_sync(0, 2e9, checkpoint)):
            items.extend(item for item in (document, node) if item)
            if next_checkpoint is not None:
                checkpoint = next_checkpoint

    expected = _prefixed(_ADMINS, custom_group_id(_DOMAIN, "g-fin"))
    assert [
        item.external_access.external_user_group_ids
        for item in items
        if item.external_access
    ] == [expected, expected]
    ops.list_folder_page.assert_not_called()
    ops.list_users.assert_called_once()


def test_doc_sync_listing_keeps_bare_ids_on_documents_only() -> None:
    connector, _ops = _perm_sync_connector()

    items = [
        item for batch in connector.retrieve_all_slim_docs_perm_sync() for item in batch
    ]

    bare = {_ADMINS, custom_group_id(_DOMAIN, "g-fin")}
    slim = [item for item in items if isinstance(item, SlimDocument)]
    nodes = [item for item in items if isinstance(item, HierarchyNode)]
    assert [
        s.external_access.external_user_group_ids for s in slim if s.external_access
    ] == [bare]
    assert [
        n.external_access.external_user_group_ids for n in nodes if n.external_access
    ] == [_prefixed(*bare)]


def test_private_folders_skip_the_permissions_listing_in_any_case() -> None:
    ops = MagicMock()
    ops.list_users.return_value = []
    ops.list_groups.return_value = []
    ops.list_folder_page.return_value = EgnyteFolderPage(
        folder=EgnyteFolder(name="Private", path="/Private", folder_id="f-private"),
        folders=[],
        files=[],
    )
    connector = EgnyteConnector(folder_path="/private")
    connector.load_credentials({"domain": _DOMAIN, "access_token": "test-token"})
    connector._ops = ops

    nodes = [
        item for batch in connector.retrieve_all_slim_docs_perm_sync() for item in batch
    ]

    ops.list_folder_page_with_permissions.assert_not_called()
    assert [
        n.external_access.external_user_group_ids for n in nodes if n.external_access
    ] == [_prefixed(_ADMINS)]


def test_a_permission_run_resuming_mid_folder_reads_the_folder_access() -> None:
    connector, ops = _perm_sync_connector()
    # Saved by a run without permissions, on the folder's second page.
    checkpoint = EgnyteCheckpoint(
        has_more=True, todo=[], current_path="/Shared", offset=180
    )

    documents = [
        document
        for document, _node, _failure, _next in CheckpointOutputWrapper[
            EgnyteCheckpoint
        ]()(connector.load_from_checkpoint_with_perm_sync(0, 2e9, checkpoint))
        if document
    ]

    assert ops.list_folder_page_with_permissions.call_args.kwargs["offset"] == 180
    assert [
        d.external_access.external_user_group_ids
        for d in documents
        if d.external_access
    ] == [_prefixed(_ADMINS, custom_group_id(_DOMAIN, "g-fin"))]


def test_group_sync_validation_does_not_read_the_folder() -> None:
    connector, _ = _perm_sync_connector()
    ops = MagicMock(spec=EgnyteSourceOperations)
    ops.get_user_info.return_value = EgnyteUserInfo(
        username="root", user_type=EgnyteUserType.ADMIN
    )
    ops.list_groups.return_value = [EgnyteGroupRef(id="g-fin", display_name="Finance")]
    ops.get_group.return_value = EgnyteGroup(id="g-fin", display_name="Finance")
    connector._ops = ops

    validate_egnyte_group_sync(connector)

    ops.list_folder_page_with_permissions.assert_not_called()
    ops.list_folder_page.assert_not_called()
