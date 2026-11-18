"""Drive converts a conversion target from the file fields its listing stored:
no metadata fetch, readers rotated by file id, the listing user and the admin
kept as fallbacks. A target with no stored fields goes through reindex."""

from collections.abc import Generator, Iterable
from typing import cast
from unittest.mock import MagicMock, patch

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.google_drive.connector import GoogleDriveConnector
from onyx.connectors.google_drive.doc_conversion import MAX_RETRIEVER_EMAILS
from onyx.connectors.google_drive.models import DriveBatchResult, DriveListingPayload
from onyx.connectors.google_drive.source_operations import (
    GoogleDriveHttpError,
    GoogleDriveRefreshError,
    GoogleDriveSourceOperations,
)
from onyx.connectors.models import (
    ConnectorFailure,
    Document,
    HierarchyNode,
    ResolveTarget,
    TextSection,
)

_CONN_MODULE = "onyx.connectors.google_drive.connector"


def _make_connector() -> GoogleDriveConnector:
    connector = GoogleDriveConnector(include_my_drives=True)
    connector._ops = MagicMock(spec=GoogleDriveSourceOperations)
    connector._primary_admin_email = "admin@example.com"
    return connector


def _target(file_id: str, readers: list[str]) -> ResolveTarget:
    return ResolveTarget(
        document_id=f"https://docs.google.com/document/d/{file_id}",
        listing_payload=DriveListingPayload(
            retriever_email="lister@example.com",
            drive_file={"id": file_id, "name": file_id},
            reader_emails=readers,
            folder_path=["My Drive", "Projects"],
        ),
    )


def _doc(file_id: str) -> Document:
    return Document(
        id=file_id,
        sections=[TextSection(text="x")],
        source=DocumentSource.GOOGLE_DRIVE,
        semantic_identifier=file_id,
        metadata={},
    )


def test_listed_targets_convert_without_reindex() -> None:
    connector = _make_connector()
    calls: list[tuple[str, list[str]]] = []

    def fake_convert(
        _ops: object,
        _allow_images: bool,
        _size_threshold: int,
        _ctx: object,
        retriever_emails: list[str],
        file: dict,
        _callback: object,
        folder_path: list[str] | None,
        _path_readers: object = (),
    ) -> Document:
        assert folder_path == ["My Drive", "Projects"]
        calls.append((file["id"], retriever_emails))
        return _doc(file["id"])

    readers = [f"user{i}@example.com" for i in range(4)]
    targets = [_target(f"file-{i}", readers) for i in range(20)]
    with (
        patch(f"{_CONN_MODULE}.convert_drive_item_to_document", fake_convert),
        patch.object(connector, "reindex") as reindex,
    ):
        docs = list(connector.resolve_targets(targets))

    reindex.assert_not_called()
    assert sorted(d.id for d in docs if isinstance(d, Document)) == sorted(
        f"file-{i}" for i in range(20)
    )
    first_readers = {emails[0] for _, emails in calls}
    # Reads spread over more than one user.
    assert len(first_readers) > 1
    for _, emails in calls:
        assert set(emails) == {*readers, "lister@example.com", "admin@example.com"}
        # The listing user, then the admin, are the last fallbacks.
        assert emails[-2:] == ["lister@example.com", "admin@example.com"]


def test_unlisted_target_goes_through_reindex() -> None:
    connector = _make_connector()
    seen: list[list[ConnectorFailure]] = []

    def fake_reindex(
        errors: list[ConnectorFailure], include_permissions: bool = False
    ) -> Generator[Document | ConnectorFailure | HierarchyNode, None, None]:
        assert include_permissions
        seen.append(errors)
        yield from ()

    with patch.object(connector, "reindex", side_effect=fake_reindex):
        list(
            connector.resolve_targets(
                [ResolveTarget(document_id="https://docs.google.com/x")],
                include_permissions=True,
            )
        )

    assert len(seen) == 1
    assert seen[0][0].failed_document is not None
    assert seen[0][0].failed_document.document_id == "https://docs.google.com/x"


def test_reader_list_stays_under_the_retriever_limit() -> None:
    connector = _make_connector()
    calls: list[list[str]] = []

    def fake_convert(*args: object) -> None:
        calls.append(cast(list[str], args[4]))
        return None

    readers = [f"user{i}@example.com" for i in range(MAX_RETRIEVER_EMAILS * 2)]
    with patch(f"{_CONN_MODULE}.convert_drive_item_to_document", fake_convert):
        list(connector.resolve_targets([_target("file-x", readers)]))

    assert len(calls[0]) == MAX_RETRIEVER_EMAILS
    assert calls[0][-2:] == ["lister@example.com", "admin@example.com"]


def _permission_batch(
    files: dict[str, dict[str, object]], errors: dict[str, Exception] | None = None
) -> DriveBatchResult:
    return DriveBatchResult(files=files, errors=errors or {})


def test_permissions_are_read_for_the_batch_not_through_reindex() -> None:
    """The listing has no permission fields. Conversion reads them with one
    batch request for each listing user, and converts from the payload."""
    connector = _make_connector()
    ops = cast(MagicMock, connector.ops)
    ops.batch_get_files.return_value = _permission_batch(
        {
            "file-a": {"id": "file-a", "permissionIds": ["p1"]},
            "file-b": {"id": "file-b", "permissionIds": ["p2"]},
        }
    )
    converted: list[dict[str, object]] = []

    def convert(*args: object, **_kwargs: object) -> Document:
        drive_file = cast(dict[str, object], args[5])
        converted.append(drive_file)
        return _doc(str(drive_file["id"]))

    with (
        patch(f"{_CONN_MODULE}.convert_drive_item_to_document", side_effect=convert),
        patch.object(connector, "reindex", return_value=iter([])) as reindex,
    ):
        results = list(
            connector.resolve_targets(
                [_target("file-a", []), _target("file-b", [])],
                include_permissions=True,
            )
        )

    assert len(results) == 2
    reindex.assert_not_called()
    ops.batch_get_files.assert_called_once()
    assert ops.batch_get_files.call_args.kwargs["user_email"] == "lister@example.com"
    assert sorted(ops.batch_get_files.call_args.kwargs["file_ids_by_key"]) == [
        "file-a",
        "file-b",
    ]
    assert {str(f["id"]): f["permissionIds"] for f in converted} == {
        "file-a": ["p1"],
        "file-b": ["p2"],
    }


def test_no_permission_read_without_permission_sync() -> None:
    connector = _make_connector()
    with patch(
        f"{_CONN_MODULE}.convert_drive_item_to_document", return_value=_doc("file-a")
    ):
        list(connector.resolve_targets([_target("file-a", [])]))

    cast(MagicMock, connector.ops).batch_get_files.assert_not_called()


def test_a_file_whose_permissions_cannot_be_read_goes_through_reindex() -> None:
    connector = _make_connector()
    cast(MagicMock, connector.ops).batch_get_files.return_value = _permission_batch(
        {"file-a": {"id": "file-a", "permissionIds": []}},
        {"file-b": RuntimeError("forbidden")},
    )
    with (
        patch(
            f"{_CONN_MODULE}.convert_drive_item_to_document",
            return_value=_doc("file-a"),
        ) as convert,
        patch.object(connector, "reindex", return_value=iter([])) as reindex,
    ):
        list(
            connector.resolve_targets(
                [_target("file-a", []), _target("file-b", [])],
                include_permissions=True,
            )
        )

    assert convert.call_count == 1
    reindex.assert_called_once()
    (failures, _include_permissions), _ = reindex.call_args
    assert [f.failed_document.document_id for f in failures] == [
        "https://docs.google.com/document/d/file-b"
    ]


def test_the_link_only_filter_applies_at_conversion() -> None:
    """With exclude_domain_link_only, the listing no longer asks for
    permissions, so conversion drops a file that is shared by link only."""
    connector = _make_connector()
    connector.exclude_domain_link_only = True
    cast(MagicMock, connector.ops).batch_get_files.return_value = _permission_batch(
        {
            "file-a": {
                "id": "file-a",
                "permissions": [{"type": "anyone", "allowFileDiscovery": False}],
            },
            "file-b": {"id": "file-b", "permissions": [{"type": "user"}]},
        }
    )
    with patch(
        f"{_CONN_MODULE}.convert_drive_item_to_document", return_value=_doc("file-b")
    ) as convert:
        results = list(
            connector.resolve_targets([_target("file-a", []), _target("file-b", [])])
        )

    assert len(results) == 1
    assert convert.call_count == 1
    assert convert.call_args.args[5]["id"] == "file-b"


def test_the_link_only_filter_reads_every_permission_first() -> None:
    """The listing gives only some permissions. The link-only one is missing
    from them, so conversion reads every permission before the filter runs,
    also without permission sync."""
    connector = _make_connector()
    connector.exclude_domain_link_only = True
    ops = cast(MagicMock, connector.ops)
    ops.batch_get_files.return_value = _permission_batch(
        {
            "file-a": {
                "id": "file-a",
                "permissions": [{"id": "p1", "type": "user"}],
                "permissionIds": ["p1", "p2"],
            }
        }
    )
    ops.list_file_permissions.return_value = [
        {"id": "p1", "type": "user"},
        {"id": "p2", "type": "domain", "allowFileDiscovery": False},
    ]

    with patch(f"{_CONN_MODULE}.convert_drive_item_to_document") as convert:
        results = list(connector.resolve_targets([_target("file-a", [])]))

    convert.assert_not_called()
    assert results == []


def _denied() -> GoogleDriveHttpError:
    return GoogleDriveHttpError(
        status_code=403,
        reasons=("insufficientFilePermissions",),
        access_denied=True,
        message="denied",
    )


def _shared_drive_target(file_id: str, readers: list[str]) -> ResolveTarget:
    target = _target(file_id, readers)
    payload = cast(DriveListingPayload, target.listing_payload)
    payload.drive_file = {"id": file_id, "name": file_id, "driveId": "drive-1"}
    return target


_PERMISSIONS: list[dict[str, object]] = [
    {"id": "p1", "type": "user", "emailAddress": "a@example.com"},
    {
        "id": "p2",
        "type": "group",
        "emailAddress": "team@example.com",
        "permissionDetails": [
            {
                "permissionType": "member",
                "inherited": True,
                "inheritedFrom": "drive-1",
            }
        ],
    },
]


def test_permissions_given_only_by_id_are_read_as_a_user_who_can() -> None:
    """The batch read gives the permission ids but not the permissions. The
    listing user cannot read them; a drive member can. Conversion gets every
    permission, so the document keeps the drive's members and groups."""
    connector = _make_connector()
    ops = cast(MagicMock, connector.ops)
    ops.batch_get_files.return_value = _permission_batch(
        {"file-a": {"id": "file-a", "permissionIds": ["p1", "p2"]}}
    )

    def list_file_permissions(
        *, user_email: str, file_id: str, **_kwargs: object
    ) -> list[dict[str, object]]:
        assert file_id == "file-a"
        if user_email != "member@example.com":
            raise _denied()
        return _PERMISSIONS

    ops.list_file_permissions.side_effect = list_file_permissions
    converted: list[dict[str, object]] = []

    def convert(*args: object, **_kwargs: object) -> Document:
        drive_file = cast(dict[str, object], args[5])
        converted.append(drive_file)
        return _doc(str(drive_file["id"]))

    with patch(f"{_CONN_MODULE}.convert_drive_item_to_document", side_effect=convert):
        results = list(
            connector.resolve_targets(
                [_shared_drive_target("file-a", ["member@example.com"])],
                include_permissions=True,
            )
        )

    assert [type(r) for r in results] == [Document]
    assert converted[0]["permissions"] == _PERMISSIONS
    # The listing user is asked first.
    assert (
        ops.list_file_permissions.call_args_list[0].kwargs["user_email"]
        == "lister@example.com"
    )


def test_a_shared_drive_file_with_unreadable_permissions_fails_closed() -> None:
    """No reader can read the permissions of a shared drive file. Converting
    it would give access to one user and drop the drive's members, so it
    becomes a failure and is not converted."""
    connector = _make_connector()
    ops = cast(MagicMock, connector.ops)
    ops.batch_get_files.return_value = _permission_batch(
        {"file-a": {"id": "file-a", "permissionIds": ["p1", "p2"]}}
    )
    ops.list_file_permissions.side_effect = _denied()

    with patch(f"{_CONN_MODULE}.convert_drive_item_to_document") as convert:
        results = list(
            connector.resolve_targets(
                [_shared_drive_target("file-a", ["member@example.com"])],
                include_permissions=True,
            )
        )

    convert.assert_not_called()
    assert len(results) == 1
    failure = results[0]
    assert isinstance(failure, ConnectorFailure)
    assert failure.failed_document is not None
    assert failure.failed_document.document_id == (
        "https://docs.google.com/document/d/file-a"
    )


def test_a_partial_permission_read_fails_closed() -> None:
    connector = _make_connector()
    ops = cast(MagicMock, connector.ops)
    ops.batch_get_files.return_value = _permission_batch(
        {"file-a": {"id": "file-a", "permissionIds": ["p1", "p2"]}}
    )
    ops.list_file_permissions.return_value = _PERMISSIONS[:1]

    with patch(f"{_CONN_MODULE}.convert_drive_item_to_document") as convert:
        results = list(
            connector.resolve_targets(
                [_target("file-a", ["member@example.com"])],
                include_permissions=True,
            )
        )

    convert.assert_not_called()
    assert [type(r) for r in results] == [ConnectorFailure]


def test_a_failed_permission_read_fails_closed() -> None:
    connector = _make_connector()
    ops = cast(MagicMock, connector.ops)
    ops.batch_get_files.return_value = _permission_batch(
        {"file-a": {"id": "file-a", "permissionIds": ["p1"]}}
    )
    ops.list_file_permissions.side_effect = GoogleDriveHttpError(
        status_code=500, reasons=(), access_denied=False, message="backend error"
    )

    with patch(f"{_CONN_MODULE}.convert_drive_item_to_document") as convert:
        results = list(
            connector.resolve_targets([_target("file-a", [])], include_permissions=True)
        )

    convert.assert_not_called()
    assert [type(r) for r in results] == [ConnectorFailure]


def test_a_shared_drive_file_skips_the_batch_permission_read() -> None:
    """Drive never gives `permissions` for a shared drive file, so the batch
    files.get would only spend quota. Conversion reads the permissions with
    one permissions.list, as the listing user, and batch-reads only the
    other files."""
    connector = _make_connector()
    ops = cast(MagicMock, connector.ops)
    ops.batch_get_files.return_value = _permission_batch(
        {"file-b": {"id": "file-b", "permissionIds": ["p1"]}}
    )
    ops.list_file_permissions.return_value = _PERMISSIONS
    converted: list[dict[str, object]] = []

    def convert(*args: object, **_kwargs: object) -> Document:
        drive_file = cast(dict[str, object], args[5])
        converted.append(drive_file)
        return _doc(str(drive_file["id"]))

    with patch(f"{_CONN_MODULE}.convert_drive_item_to_document", side_effect=convert):
        results = list(
            connector.resolve_targets(
                [
                    _shared_drive_target("file-a", ["member@example.com"]),
                    _target("file-b", []),
                ],
                include_permissions=True,
            )
        )

    assert [type(r) for r in results] == [Document, Document]
    ops.batch_get_files.assert_called_once()
    assert list(ops.batch_get_files.call_args.kwargs["file_ids_by_key"]) == ["file-b"]
    shared_reads = [
        call
        for call in ops.list_file_permissions.call_args_list
        if call.kwargs["file_id"] == "file-a"
    ]
    assert len(shared_reads) == 1
    assert shared_reads[0].kwargs["user_email"] == "lister@example.com"
    by_id = {str(f["id"]): f for f in converted}
    assert by_id["file-a"]["permissions"] == _PERMISSIONS


def test_a_listing_user_that_cannot_be_impersonated_sends_its_files_to_reindex() -> (
    None
):
    """The batch read of one listing user fails on its credentials. Its files
    go through reindex, and the other users' files still convert."""
    connector = _make_connector()
    ops = cast(MagicMock, connector.ops)

    def batch_get_files(*, user_email: str, **_kwargs: object) -> DriveBatchResult:
        if user_email == "gone@example.com":
            raise GoogleDriveRefreshError("cannot impersonate")
        return _permission_batch(
            {"file-a": {"id": "file-a", "permissions": [_PERMISSIONS[0]]}}
        )

    ops.batch_get_files.side_effect = batch_get_files
    gone = _target("file-b", [])
    cast(DriveListingPayload, gone.listing_payload).retriever_email = "gone@example.com"

    with (
        patch(
            f"{_CONN_MODULE}.convert_drive_item_to_document",
            return_value=_doc("file-a"),
        ) as convert,
        patch.object(connector, "reindex", return_value=iter([])) as reindex,
    ):
        results = list(
            connector.resolve_targets(
                [_target("file-a", []), gone], include_permissions=True
            )
        )

    assert [type(r) for r in results] == [Document]
    assert convert.call_count == 1
    (failures, _include_permissions), _ = reindex.call_args
    assert [f.failed_document.document_id for f in failures] == [
        "https://docs.google.com/document/d/file-b"
    ]


def test_a_permission_read_again_replaces_the_stored_one() -> None:
    """The batch read gives p1 shared with discovery on, and only the id of
    p2. permissions.list gives p1 with discovery now off. The link-only
    filter uses the newer p1 and drops the file."""
    connector = _make_connector()
    connector.exclude_domain_link_only = True
    ops = cast(MagicMock, connector.ops)
    ops.batch_get_files.return_value = _permission_batch(
        {
            "file-a": {
                "id": "file-a",
                "permissions": [
                    {"id": "p1", "type": "domain", "allowFileDiscovery": True}
                ],
                "permissionIds": ["p1", "p2"],
            }
        }
    )
    ops.list_file_permissions.return_value = [
        {"id": "p1", "type": "domain", "allowFileDiscovery": False},
        {"id": "p2", "type": "user"},
    ]

    with patch(f"{_CONN_MODULE}.convert_drive_item_to_document") as convert:
        results = list(connector.resolve_targets([_target("file-a", [])]))

    convert.assert_not_called()
    assert results == []


def test_stored_readers_outside_the_user_limit_are_not_impersonated() -> None:
    """specific_user_emails limits the users the connector acts as. A stored
    reader outside it reads nothing at conversion: not the content, the
    permissions or the folder path."""
    connector = GoogleDriveConnector(
        include_my_drives=True,
        specific_user_emails="lister@example.com,alice@example.com",
    )
    connector._ops = MagicMock(spec=GoogleDriveSourceOperations)
    connector._primary_admin_email = "admin@example.com"
    ops = cast(MagicMock, connector.ops)
    ops.list_file_permissions.side_effect = _denied()
    target = _shared_drive_target("file-a", ["bob@example.com", "alice@example.com"])
    payload = cast(DriveListingPayload, target.listing_payload)
    payload.folder_path = None
    retrievers: list[list[str]] = []
    recorded: list[list[str]] = []

    def build_path(
        *_args: object, path_readers: Iterable[str] = (), **_kwargs: object
    ) -> list[str]:
        recorded.append(list(path_readers))
        return ["Team"]

    def convert(*args: object, **_kwargs: object) -> Document:
        retrievers.append(cast(list[str], args[4]))
        return _doc("file-a")

    with (
        patch(f"{_CONN_MODULE}.convert_drive_item_to_document", side_effect=convert),
        patch(f"{_CONN_MODULE}.build_folder_path", side_effect=build_path),
        patch.object(connector, "_drive_member_emails", return_value=[]),
    ):
        list(connector.resolve_targets([target], include_permissions=False))

    assert retrievers and "bob@example.com" not in retrievers[0]
    assert "alice@example.com" in retrievers[0]
    assert recorded and "bob@example.com" not in recorded[0]


def test_a_listing_user_outside_the_user_limit_sends_its_file_to_reindex() -> None:
    connector = GoogleDriveConnector(
        include_my_drives=True, specific_user_emails="alice@example.com"
    )
    connector._ops = MagicMock(spec=GoogleDriveSourceOperations)
    connector._primary_admin_email = "admin@example.com"

    with (
        patch(f"{_CONN_MODULE}.convert_drive_item_to_document") as convert,
        patch.object(connector, "reindex", return_value=iter(())) as reindex,
    ):
        list(connector.resolve_targets([_target("file-a", ["alice@example.com"])]))

    convert.assert_not_called()
    reindex.assert_called_once()


@pytest.mark.parametrize(
    "permissions",
    [
        pytest.param([], id="empty"),
        pytest.param(_PERMISSIONS[:1], id="no-member"),
    ],
)
def test_a_shared_drive_permission_read_with_no_member_fails_closed(
    permissions: list[dict[str, object]],
) -> None:
    """A shared drive file always has the drive's members. A read that gives
    none of them is not complete: the document would leave them out."""
    connector = _make_connector()
    ops = cast(MagicMock, connector.ops)
    ops.list_file_permissions.return_value = permissions

    with patch(f"{_CONN_MODULE}.convert_drive_item_to_document") as convert:
        results = list(
            connector.resolve_targets(
                [_shared_drive_target("file-a", ["member@example.com"])],
                include_permissions=True,
            )
        )

    convert.assert_not_called()
    assert [type(r) for r in results] == [ConnectorFailure]


def test_a_folder_path_error_fails_only_its_target() -> None:
    """The folder path of a target with no stored path is read at
    conversion. An error there fails that target, and the other targets of
    the batch still convert."""
    connector = _make_connector()
    broken = _target("file-a", [])
    cast(DriveListingPayload, broken.listing_payload).folder_path = None

    with (
        patch(
            f"{_CONN_MODULE}.convert_drive_item_to_document",
            side_effect=lambda *args, **_kwargs: _doc(str(args[5]["id"])),
        ),
        patch(
            f"{_CONN_MODULE}.build_folder_path",
            side_effect=ConnectionResetError("reset"),
        ),
    ):
        results = list(connector.resolve_targets([broken, _target("file-b", [])]))

    assert sorted(type(r).__name__ for r in results) == [
        "ConnectorFailure",
        "Document",
    ]
    failure = next(r for r in results if isinstance(r, ConnectorFailure))
    assert failure.failed_document is not None
    assert failure.failed_document.document_id == (
        "https://docs.google.com/document/d/file-a"
    )
