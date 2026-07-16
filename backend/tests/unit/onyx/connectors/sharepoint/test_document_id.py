"""Unit tests for SharePoint file Document.id minting (unique-ID GUID)."""

import logging
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.connectors.sharepoint.connector import _convert_driveitem_to_slim_document
from onyx.connectors.sharepoint.connector import DriveItemData
from tests.utils.sharepoint import make_drive_item_id

_GUID = "2ab3c4d5-6e7f-4a1b-9c0d-1e2f3a4b5c6d"
_OTHER_GUID = "0320e240-b69f-4d8d-a196-89674cd60485"


def _make_driveitem(
    item_id: str | None = None,
    list_item_unique_id: str | None = None,
) -> DriveItemData:
    return DriveItemData(
        id=item_id if item_id is not None else make_drive_item_id(_GUID),
        name="doc.docx",
        web_url="https://acme.sharepoint.com/sites/eng/doc.docx",
        drive_id="drive-1",
        list_item_unique_id=list_item_unique_id,
    )


def test_from_graph_json_parses_list_item_unique_id() -> None:
    item = DriveItemData.from_graph_json(
        {
            "id": make_drive_item_id(_GUID),
            "name": "doc.docx",
            "webUrl": "https://acme.sharepoint.com/sites/eng/doc.docx",
            "sharepointIds": {"listItemUniqueId": _GUID},
        }
    )
    assert item.list_item_unique_id == _GUID


def test_document_id_derived_from_drive_item_id() -> None:
    assert _make_driveitem().document_id() == _GUID


def test_document_id_prefers_declared_guid_and_warns_on_mismatch(
    caplog: pytest.LogCaptureFixture,
) -> None:
    driveitem = _make_driveitem(list_item_unique_id=_OTHER_GUID.upper())
    with caplog.at_level(logging.WARNING):
        assert driveitem.document_id() == _OTHER_GUID
    assert "declares" in caplog.text


def test_document_id_no_warning_when_declared_matches_derived(
    caplog: pytest.LogCaptureFixture,
) -> None:
    driveitem = _make_driveitem(list_item_unique_id=_GUID.upper())
    with caplog.at_level(logging.WARNING):
        assert driveitem.document_id() == _GUID
    assert caplog.text == ""


def test_document_id_uses_derived_when_declared_is_malformed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    driveitem = _make_driveitem(list_item_unique_id="not-a-guid")
    with caplog.at_level(logging.WARNING):
        assert driveitem.document_id() == _GUID
    assert "Malformed" in caplog.text


def test_document_id_falls_back_to_raw_id_when_underivable(
    caplog: pytest.LogCaptureFixture,
) -> None:
    driveitem = _make_driveitem(item_id="weird-id")
    with caplog.at_level(logging.ERROR):
        assert driveitem.document_id() == "weird-id"
    assert "falling back" in caplog.text


def test_document_id_uses_declared_when_underivable() -> None:
    driveitem = _make_driveitem(item_id="weird-id", list_item_unique_id=_GUID)
    assert driveitem.document_id() == _GUID


@patch("onyx.connectors.sharepoint.connector.get_sharepoint_external_access")
def test_slim_document_conversion_emits_guid(mock_access: MagicMock) -> None:
    from onyx.connectors.models import ExternalAccess

    mock_access.return_value = ExternalAccess.empty()
    slim = _convert_driveitem_to_slim_document(
        _make_driveitem(), "Documents", MagicMock(), MagicMock()
    )
    assert slim.id == _GUID
