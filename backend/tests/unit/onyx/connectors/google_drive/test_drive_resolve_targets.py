"""Drive converts a conversion target from the file fields its listing stored:
no metadata fetch, readers rotated by file id, the listing user and the admin
kept as fallbacks. A target with no stored fields goes through reindex."""

from collections.abc import Generator
from typing import cast
from unittest.mock import MagicMock, patch

from onyx.configs.constants import DocumentSource
from onyx.connectors.google_drive.connector import GoogleDriveConnector
from onyx.connectors.google_drive.doc_conversion import MAX_RETRIEVER_EMAILS
from onyx.connectors.google_drive.models import DriveBatchResult, DriveListingPayload
from onyx.connectors.google_drive.source_operations import (
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
