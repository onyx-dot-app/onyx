from datetime import datetime
from datetime import timezone
from typing import cast

import pytest
from box_sdk_gen import BoxClient
from box_sdk_gen.schemas.collaboration import Collaboration
from box_sdk_gen.schemas.collaboration import CollaborationRoleField
from box_sdk_gen.schemas.collaboration import CollaborationStatusField
from box_sdk_gen.schemas.file_full import FileFull
from box_sdk_gen.schemas.folder_full import FolderFull
from box_sdk_gen.schemas.folder_mini import FolderMini
from box_sdk_gen.schemas.group_mini import GroupMini
from box_sdk_gen.schemas.items import Items
from box_sdk_gen.schemas.user_collaborations import UserCollaborations
from box_sdk_gen.schemas.user_mini import UserMini

from onyx.connectors.box.connector import apply_collaborations_to_access
from onyx.connectors.box.connector import apply_shared_link_to_access
from onyx.connectors.box.connector import BoxConnector
from onyx.connectors.box.models import BoxAccessContext
from onyx.connectors.models import Document
from tests.unit.onyx.connectors.box.fake_box_client import FakeBoxClient

# Pinned spec: every Box collaboration role that can read/preview content.
# "uploader" is the single upload-only role and must NOT grant read access.
_EXPECTED_READ_ROLES = {
    CollaborationRoleField.EDITOR,
    CollaborationRoleField.VIEWER,
    CollaborationRoleField.PREVIEWER,
    CollaborationRoleField.PREVIEWER_UPLOADER,
    CollaborationRoleField.VIEWER_UPLOADER,
    CollaborationRoleField.CO_OWNER,
    CollaborationRoleField.OWNER,
}


def _user_collab(
    email: str,
    role: CollaborationRoleField,
    status: CollaborationStatusField = CollaborationStatusField.ACCEPTED,
) -> Collaboration:
    return Collaboration(
        id=f"collab-{email}-{role.value}",
        accessible_by=UserCollaborations(id="u1", login=email),
        role=role,
        status=status,
    )


def _group_collab(group_id: str) -> Collaboration:
    return Collaboration(
        id=f"collab-group-{group_id}",
        accessible_by=GroupMini(id=group_id, name="some group"),
        role=CollaborationRoleField.VIEWER,
        status=CollaborationStatusField.ACCEPTED,
    )


def test_role_completeness_against_sdk_enum() -> None:
    """If Box adds a new collaboration role, this fails so someone decides
    explicitly whether it grants read access."""
    all_roles = set(CollaborationRoleField)
    assert all_roles == _EXPECTED_READ_ROLES | {CollaborationRoleField.UPLOADER}


@pytest.mark.parametrize("role", sorted(_EXPECTED_READ_ROLES, key=lambda r: r.value))
def test_read_capable_roles_grant_access(role: CollaborationRoleField) -> None:
    access = apply_collaborations_to_access(
        BoxAccessContext(), [_user_collab("reader@example.com", role)]
    )
    assert access.user_emails == {"reader@example.com"}


def test_uploader_role_grants_nothing() -> None:
    access = apply_collaborations_to_access(
        BoxAccessContext(),
        [_user_collab("uploader@example.com", CollaborationRoleField.UPLOADER)],
    )
    assert access.user_emails == set()


@pytest.mark.parametrize(
    "status",
    [CollaborationStatusField.PENDING, CollaborationStatusField.REJECTED],
)
def test_non_accepted_collaborations_grant_nothing(
    status: CollaborationStatusField,
) -> None:
    access = apply_collaborations_to_access(
        BoxAccessContext(),
        [_user_collab("invited@example.com", CollaborationRoleField.EDITOR, status)],
    )
    assert access.user_emails == set()


def test_group_collaboration_maps_to_prefixed_group_id() -> None:
    access = apply_collaborations_to_access(BoxAccessContext(), [_group_collab("42")])
    assert access.group_ids == {"box-group-42"}
    assert access.user_emails == set()


def test_shared_link_open_is_public() -> None:
    access = apply_shared_link_to_access(
        BoxAccessContext(), "open", is_password_enabled=False
    )
    assert access.is_public is True


def test_shared_link_open_with_password_is_not_public() -> None:
    access = apply_shared_link_to_access(
        BoxAccessContext(), "open", is_password_enabled=True
    )
    assert access.is_public is False


def test_shared_link_company_maps_to_enterprise_group() -> None:
    access = apply_shared_link_to_access(
        BoxAccessContext(), "company", is_password_enabled=False
    )
    assert access.is_public is False
    assert access.group_ids == {"box-enterprise-all-users"}


def test_shared_link_collaborators_grants_nothing() -> None:
    access = apply_shared_link_to_access(
        BoxAccessContext(), "collaborators", is_password_enabled=False
    )
    assert access.is_public is False
    assert access.group_ids == set()
    assert access.user_emails == set()


def test_access_context_merge_is_a_union() -> None:
    merged = BoxAccessContext(
        user_emails={"a@example.com"}, group_ids={"box-group-1"}
    ).merged_with(
        BoxAccessContext(
            user_emails={"b@example.com"},
            group_ids={"box-group-2"},
            is_public=True,
        )
    )
    assert merged.user_emails == {"a@example.com", "b@example.com"}
    assert merged.group_ids == {"box-group-1", "box-group-2"}
    assert merged.is_public is True


def _perm_sync_fake_client() -> FakeBoxClient:
    """Root (100, collaborated to root-viewer) -> Sub (200, collaborated to
    sub-viewer) containing shared.txt (own collab: file-viewer) and plain.txt
    (no own collabs)."""
    modified = datetime(2024, 6, 1, tzinfo=timezone.utc)
    owner = UserMini(id="u0", name="Owner", login="owner@example.com")
    shared_file = FileFull(
        id="1",
        name="shared.txt",
        size=5,
        modified_at=modified,
        owned_by=owner,
        has_collaborations=True,
    )
    plain_file = FileFull(
        id="2",
        name="plain.txt",
        size=5,
        modified_at=modified,
        owned_by=owner,
        has_collaborations=False,
    )
    return FakeBoxClient(
        folders_by_id={
            "100": FolderFull(id="100", name="Root"),
            "200": FolderFull(id="200", name="Sub"),
        },
        pages={
            ("100", None): Items(
                entries=[FolderMini(id="200", name="Sub")], next_marker=None
            ),
            ("200", None): Items(entries=[shared_file, plain_file], next_marker=None),
        },
        file_contents={"1": b"shared", "2": b"plain"},
        folder_collaborations={
            "100": [
                _user_collab("root-viewer@example.com", CollaborationRoleField.VIEWER)
            ],
            "200": [
                _user_collab("sub-viewer@example.com", CollaborationRoleField.VIEWER)
            ],
        },
        file_collaborations={
            "1": [
                _user_collab("file-viewer@example.com", CollaborationRoleField.VIEWER)
            ],
        },
    )


def test_perm_sync_traversal_inherits_ancestor_collaborations() -> None:
    fake_client = _perm_sync_fake_client()
    connector = BoxConnector(folder_ids=["100"])
    connector._client = cast(BoxClient, fake_client)
    connector._enterprise_client = cast(BoxClient, fake_client)

    checkpoint = connector.build_dummy_checkpoint()
    documents: list[Document] = []
    while checkpoint.has_more:
        generator = connector.load_from_checkpoint_with_perm_sync(0, 2**31, checkpoint)
        while True:
            try:
                item = next(generator)
            except StopIteration as e:
                checkpoint = connector.validate_checkpoint_json(
                    e.value.model_dump_json()
                )
                break
            if isinstance(item, Document):
                documents.append(item)

    by_id = {d.id: d for d in documents}
    assert set(by_id) == {"box-file-1", "box-file-2"}

    plain_access = by_id["box-file-2"].external_access
    assert plain_access is not None
    # folder owner + root collab (inherited) + sub collab, but NOT the
    # file-level collab that belongs to shared.txt only
    assert plain_access.external_user_emails == {
        "owner@example.com",
        "root-viewer@example.com",
        "sub-viewer@example.com",
    }
    assert plain_access.is_public is False

    shared_access = by_id["box-file-1"].external_access
    assert shared_access is not None
    assert shared_access.external_user_emails == {
        "owner@example.com",
        "root-viewer@example.com",
        "sub-viewer@example.com",
        "file-viewer@example.com",
    }

    # file-level collaborations were fetched only for the file that has them
    assert fake_client.list_collaborations.file_collaboration_calls == ["1"]


def test_non_perm_sync_traversal_makes_no_permission_calls() -> None:
    fake_client = _perm_sync_fake_client()
    connector = BoxConnector(folder_ids=["100"])
    connector._client = cast(BoxClient, fake_client)
    connector._enterprise_client = cast(BoxClient, fake_client)

    checkpoint = connector.build_dummy_checkpoint()
    while checkpoint.has_more:
        generator = connector.load_from_checkpoint(0, 2**31, checkpoint)
        while True:
            try:
                item = next(generator)
            except StopIteration as e:
                checkpoint = e.value
                break
            if isinstance(item, Document):
                assert item.external_access is None

    assert fake_client.list_collaborations.file_collaboration_calls == []
