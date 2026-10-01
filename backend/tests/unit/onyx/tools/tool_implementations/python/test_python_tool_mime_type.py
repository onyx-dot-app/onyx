from unittest.mock import patch

import pytest

from onyx.file_processing.file_types import (
    PRESENTATION_MIME_TYPE,
    SPREADSHEET_MIME_TYPE,
    WORD_PROCESSING_MIME_TYPE,
)
from onyx.tools.tool_implementations.python.python_tool import (
    guess_output_file_mime_type,
)


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("report.xlsx", SPREADSHEET_MIME_TYPE),
        ("REPORT.XLSX", SPREADSHEET_MIME_TYPE),
        ("memo.docx", WORD_PROCESSING_MIME_TYPE),
        ("deck.pptx", PRESENTATION_MIME_TYPE),
    ],
)
def test_office_files_resolve_without_system_mime_types(
    filename: str, expected: str
) -> None:
    # Simulate an image without /etc/mime.types.
    with patch("mimetypes.guess_type", return_value=(None, None)):
        assert guess_output_file_mime_type(filename) == expected


def test_other_files_use_mimetypes_then_octet_stream() -> None:
    assert guess_output_file_mime_type("chart.png") == "image/png"
    assert guess_output_file_mime_type("blob.unknownext") == "application/octet-stream"
