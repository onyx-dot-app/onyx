"""A Google Doc is read from the Docs API first. The Drive export is read
only when the Docs API sections cannot stand alone: the doc has smart chips,
its text is near the size threshold, or the Docs API read fails. Each export
is one Drive request, and Drive quota limits indexing throughput."""

from typing import Any
from unittest.mock import MagicMock

import pytest

from onyx.connectors.google_drive import doc_conversion
from onyx.connectors.google_drive.doc_conversion import (
    SMART_CHIP_CHAR,
    convert_drive_item_to_document,
)
from onyx.connectors.google_drive.models import GDriveMimeType
from onyx.connectors.google_drive.source_operations import (
    ExportSizeThresholdExceeded,
    GoogleDriveHttpError,
    GoogleDriveSourceOperations,
)
from onyx.connectors.models import ConnectorFailure, Document, TextSection

_USER = "user@example.com"
_FILE = {
    "id": "doc",
    "name": "A doc",
    "mimeType": GDriveMimeType.DOC.value,
    "webViewLink": "https://docs.google.com/document/d/doc/edit",
    "modifiedTime": "2026-10-01T00:00:00+00:00",
}


def _paragraph(text: str, heading_id: str | None = None) -> dict[str, Any]:
    style: dict[str, str] = {"namedStyleType": "NORMAL_TEXT"}
    if heading_id is not None:
        style = {"namedStyleType": "HEADING_1", "headingId": heading_id}
    return {
        "paragraph": {
            "paragraphStyle": style,
            "elements": [{"textRun": {"content": text}}],
        }
    }


def _google_doc(body: str) -> dict[str, Any]:
    return {
        "tabs": [
            {
                "tabProperties": {"tabId": "t.0"},
                "documentTab": {
                    "body": {
                        "content": [
                            _paragraph("Intro\n", "h.1"),
                            _paragraph(body),
                            _paragraph("Details\n", "h.2"),
                            _paragraph("More text\n"),
                        ]
                    }
                },
            }
        ]
    }


def _convert(
    ops: MagicMock, size_threshold: int = 10_000
) -> Document | ConnectorFailure | None:
    return convert_drive_item_to_document(
        ops,
        allow_images=False,
        size_threshold=size_threshold,
        permission_sync_context=None,
        retriever_emails=[_USER],
        file=dict(_FILE),
    )


def _ops(google_doc: dict[str, Any] | None, export: bytes = b"") -> MagicMock:
    ops = MagicMock(spec=GoogleDriveSourceOperations)
    ops.fetch_google_doc.return_value = google_doc
    ops.export_file.return_value = export
    return ops


def test_a_doc_without_smart_chips_is_not_exported() -> None:
    ops = _ops(_google_doc("Body text\n"))

    result = _convert(ops)

    assert isinstance(result, Document)
    ops.fetch_google_doc.assert_called_once()
    ops.export_file.assert_not_called()
    assert [section.link for section in result.sections] == [
        "https://docs.google.com/document/d/doc/edit?tab=t.0#heading=h.1",
        "https://docs.google.com/document/d/doc/edit?tab=t.0#heading=h.2",
    ]


def test_a_doc_with_smart_chips_is_exported_for_their_text() -> None:
    ops = _ops(
        _google_doc(f"Due {SMART_CHIP_CHAR}\n"),
        export=b"Intro\nDue Nov 17, 2026\nDetails\nMore text\n",
    )

    result = _convert(ops)

    assert isinstance(result, Document)
    ops.export_file.assert_called_once()
    text = "".join(
        section.text for section in result.sections if isinstance(section, TextSection)
    )
    assert "Nov 17, 2026" in text
    assert len(result.sections) == 2


def test_a_doc_near_the_size_threshold_is_exported_for_the_size_skip() -> None:
    """The export decides the size skip, as before the Docs API came first."""
    ops = _ops(_google_doc("x" * 600 + "\n"))
    ops.export_file.side_effect = ExportSizeThresholdExceeded("too large")

    result = _convert(ops, size_threshold=1_000)

    assert result is None
    ops.export_file.assert_called_once()


def test_a_doc_with_many_sections_near_the_size_threshold_is_exported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The size skip comes before the section limit: a doc with too many
    sections to align still gets the export's size check."""
    monkeypatch.setattr(doc_conversion, "ADVANCED_PARSE_MAX_SECTIONS", 1)
    ops = _ops(_google_doc("x" * 600 + "\n"))
    ops.export_file.side_effect = ExportSizeThresholdExceeded("too large")

    result = _convert(ops, size_threshold=1_000)

    assert result is None
    ops.export_file.assert_called_once()


def test_a_failed_docs_read_falls_back_to_the_export() -> None:
    ops = _ops(None, export=b"basic text")
    ops.fetch_google_doc.side_effect = GoogleDriveHttpError(
        status_code=403,
        reasons=("accessNotConfigured",),
        access_denied=True,
        message="Docs API disabled",
    )

    result = _convert(ops)

    assert isinstance(result, Document)
    ops.export_file.assert_called_once()
    assert [section.text for section in result.sections] == ["basic text"]


def test_an_oversized_docs_read_falls_back_to_the_export() -> None:
    ops = _ops(None, export=b"basic text")

    result = _convert(ops)

    assert isinstance(result, Document)
    ops.export_file.assert_called_once()
    assert [section.text for section in result.sections] == ["basic text"]
