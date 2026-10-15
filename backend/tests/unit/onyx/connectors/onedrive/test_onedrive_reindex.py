"""Filter parity of OneDriveConnector.reindex with the crawl, on mocked Graph data."""

from typing import Any
from unittest.mock import create_autospec

import pytest

from onyx.connectors.microsoft_utils.drive_delta import DriveDeltaItem
from onyx.connectors.microsoft_utils.drive_items import DriveItemContent
from onyx.connectors.microsoft_utils.graph_errors import (
    MicrosoftGraphError as OneDriveGraphError,
)
from onyx.connectors.models import (
    ConnectorFailure,
    Document,
    DocumentFailure,
    HierarchyNode,
    TextSection,
)
from onyx.connectors.onedrive.connector import (
    OneDriveConnector,
    drive_root_id,
    hierarchy_item_id,
    personal_site_from_link,
)
from onyx.connectors.onedrive.models import (
    OneDriveDrive,
    OneDrivePersonalDrive,
    OneDriveUser,
)
from onyx.connectors.onedrive.source_operations import OneDriveSourceOperations

OWNER = OneDriveUser(id="owner-id", user_principal_name="owner@example.com")
DRIVE = OneDriveDrive(id="drive-1", name="OneDrive")
SITE_LINK = (
    "https://example-my.sharepoint.com/personal/owner_example_com/_layouts/15/"
    "Doc.aspx?sourcedoc=%7Babc%7D&file=report.txt"
)
ITEM_ID = "item-1"
FOLDER_ID = "folder-1"


def _item(
    *, name: str = "report.txt", folder: str = "Folder", **extra: Any
) -> DriveDeltaItem:
    return DriveDeltaItem.model_validate(
        {
            "id": ITEM_ID,
            "name": name,
            "webUrl": SITE_LINK,
            "size": 4,
            "file": {"mimeType": "text/plain"},
            "parentReference": {
                "driveId": DRIVE.id,
                "id": FOLDER_ID,
                "path": f"/drives/{DRIVE.id}/root:/{folder}",
            },
            **extra,
        }
    )


def _folder() -> DriveDeltaItem:
    return DriveDeltaItem.model_validate(
        {
            "id": FOLDER_ID,
            "name": "Folder",
            "folder": {"childCount": 1},
            "parentReference": {
                "driveId": DRIVE.id,
                "id": "root-id",
                "path": f"/drives/{DRIVE.id}/root:",
            },
        }
    )


def _connector(
    item: DriveDeltaItem | None,
    *,
    users: list[str] | None = None,
    excluded_paths: list[str] | None = None,
    owner: OneDriveUser | None = OWNER,
    default_drive: OneDriveDrive | None = DRIVE,
) -> tuple[OneDriveConnector, Any]:
    connector = OneDriveConnector(users=users, excluded_paths=excluded_paths)
    gateway = create_autospec(OneDriveSourceOperations, instance=True)
    gateway.get_personal_site_drive.return_value = OneDrivePersonalDrive(
        drive=DRIVE, owner_id=OWNER.id
    )
    gateway.get_user.return_value = owner
    gateway.get_default_drive.return_value = default_drive
    gateway.get_drive_item.side_effect = lambda drive_id, item_id: (  # noqa: ARG005
        _folder() if item_id == FOLDER_ID else item
    )
    gateway.download_item.return_value = DriveItemContent(
        sections=[TextSection(text="body", link=SITE_LINK)]
    )
    connector._ops = gateway
    return connector, gateway


def _run(
    connector: OneDriveConnector, link: str | None = SITE_LINK
) -> list[Document | ConnectorFailure | HierarchyNode]:
    return list(
        connector.reindex(
            [
                ConnectorFailure(
                    failed_document=DocumentFailure(
                        document_id=ITEM_ID, document_link=link
                    ),
                    failure_message="synthetic",
                )
            ]
        )
    )


def _assert_single_failure(
    results: list[Document | ConnectorFailure | HierarchyNode], fragment: str
) -> None:
    assert len(results) == 1
    failure = results[0]
    assert isinstance(failure, ConnectorFailure)
    assert failure.failed_document is not None
    assert failure.failed_document.document_id == ITEM_ID
    assert fragment in failure.failure_message


def test_personal_site_from_link() -> None:
    assert personal_site_from_link(SITE_LINK) == (
        "example-my.sharepoint.com",
        "personal/owner_example_com",
    )
    assert personal_site_from_link("https://example.com/sites/team/doc") is None
    assert personal_site_from_link("not a url") is None


def test_reindex_yields_document_and_ancestors() -> None:
    connector, _ = _connector(_item())

    results = _run(connector)

    assert [type(result) for result in results] == [
        HierarchyNode,
        HierarchyNode,
        Document,
    ]
    root, folder, document = results
    assert isinstance(root, HierarchyNode) and isinstance(folder, HierarchyNode)
    assert isinstance(document, Document)
    assert root.raw_node_id == drive_root_id(DRIVE.id)
    assert folder.raw_node_id == hierarchy_item_id(DRIVE.id, FOLDER_ID)
    assert document.id == ITEM_ID
    assert document.parent_hierarchy_raw_node_id == folder.raw_node_id


@pytest.mark.parametrize(
    ("item", "excluded_paths", "fragment"),
    [
        (_item(name="report.unknown-ext"), None, "unsupported file type"),
        (_item(folder="Secret"), ["Secret/*"], "excluded path"),
        (_item(deleted={"state": "deleted"}), None, "not in an indexed OneDrive"),
        (None, None, "not in an indexed OneDrive"),
    ],
)
def test_reindex_applies_crawl_item_filters(
    item: DriveDeltaItem | None, excluded_paths: list[str] | None, fragment: str
) -> None:
    connector, gateway = _connector(item, excluded_paths=excluded_paths)

    _assert_single_failure(_run(connector), fragment)
    gateway.download_item.assert_not_called()


def test_reindex_rejects_folder_targets() -> None:
    connector, gateway = _connector(_folder())

    _assert_single_failure(_run(connector), "not a file")
    gateway.download_item.assert_not_called()


def test_reindex_reports_content_the_crawl_skips() -> None:
    connector, gateway = _connector(_item())
    gateway.download_item.return_value = None

    results = _run(connector)

    assert not [r for r in results if isinstance(r, Document)]
    failures = [r for r in results if isinstance(r, ConnectorFailure)]
    assert len(failures) == 1
    assert "size limit" in failures[0].failure_message


def test_reindex_all_users_rejects_owner_the_crawl_skips() -> None:
    # get_user returns None for guest, disabled and nameless accounts.
    connector, gateway = _connector(_item(), owner=None)

    _assert_single_failure(_run(connector), "not an indexed user")
    gateway.get_drive_item.assert_not_called()


def test_reindex_all_users_rejects_non_default_drive() -> None:
    other = OneDriveDrive(id="other-drive", name="OneDrive")
    connector, gateway = _connector(_item(), default_drive=other)

    _assert_single_failure(_run(connector), "not its owner's default OneDrive")
    gateway.get_drive_item.assert_not_called()


def test_reindex_all_users_needs_link() -> None:
    connector, gateway = _connector(_item())

    _assert_single_failure(_run(connector, link=None), "needs the document's")
    gateway.get_drive_item.assert_not_called()


def test_reindex_configured_users_rejects_other_drive() -> None:
    other = OneDriveDrive(id="other-drive", name="OneDrive")
    connector, gateway = _connector(
        _item(), users=["owner@example.com"], default_drive=other
    )

    _assert_single_failure(_run(connector), "does not belong to a configured user")
    gateway.get_drive_item.assert_not_called()


def test_reindex_raises_errors_that_fail_the_attempt() -> None:
    connector, gateway = _connector(_item())
    gateway.get_drive_item.side_effect = OneDriveGraphError(503, "busy", "busy")

    with pytest.raises(OneDriveGraphError):
        _run(connector)
