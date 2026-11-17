from unittest.mock import MagicMock

from onyx.connectors.microsoft_utils.drive_items import DriveItemContent, DriveItemData
from onyx.connectors.models import Document, TextSection
from onyx.connectors.sharepoint.connector import (
    SiteDrive,
    _convert_driveitem_to_document_with_permissions,
)


def _convert(item: dict[str, object]) -> Document:
    driveitem = DriveItemData.from_graph_json(item)
    ops = MagicMock()
    ops.download_item.return_value = DriveItemContent(
        sections=[TextSection(link=driveitem.web_url, text="body")]
    )
    document = _convert_driveitem_to_document_with_permissions(
        driveitem=driveitem,
        drive=SiteDrive(
            drive_id="drive-1",
            display_name="Documents",
            web_url="https://example.sharepoint.com/sites/s/Shared Documents",
        ),
        ops=ops,
        site_url="https://example.sharepoint.com/sites/s",
    )
    assert isinstance(document, Document)
    return document


def test_drive_item_reports_the_graph_mime_type_and_size() -> None:
    document = _convert(
        {
            "id": "item-1",
            "name": "report.pdf",
            "webUrl": "https://example.sharepoint.com/report.pdf",
            "size": 2048,
            "file": {"mimeType": "application/pdf"},
        }
    )

    assert document.source_mime_type == "application/pdf"
    assert document.source_size_bytes == 2048


def test_drive_item_without_a_size_reports_none() -> None:
    document = _convert(
        {
            "id": "item-2",
            "name": "report.pdf",
            "webUrl": "https://example.sharepoint.com/report.pdf",
            "file": {"mimeType": "application/pdf"},
        }
    )

    assert document.source_mime_type == "application/pdf"
    assert document.source_size_bytes is None
