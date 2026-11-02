import io
from typing import IO
from unittest.mock import patch

from onyx.connectors.cross_connector_utils.tabular_section_utils import (
    CONTENT_SKIPPED_PLACEHOLDER,
)
from onyx.connectors.file.connector import _process_file
from onyx.connectors.models import TextSection


def test_skipped_spreadsheet_is_not_parsed() -> None:
    """The bytes are not a valid workbook, so any parse would fail."""
    staged: list[str] = []

    def stage(_content: IO[bytes], content_type: str) -> str:
        staged.append(content_type)
        return "staged-file"

    with patch(
        "onyx.connectors.file.connector.extract_text_and_images"
    ) as extract_text_and_images:
        documents = _process_file(
            file_id="file-1",
            file_name="Budget.xlsx",
            file=io.BytesIO(b"not a workbook"),
            metadata=None,
            pdf_pass=None,
            file_type=None,
            stage=stage,
            skip_spreadsheet_content=True,
        )

    extract_text_and_images.assert_not_called()
    assert staged == []
    assert len(documents) == 1
    assert documents[0].sections == [
        TextSection(text=CONTENT_SKIPPED_PLACEHOLDER, link="Budget.xlsx")
    ]
    # The original file stays readable by the Python tool.
    assert documents[0].file_id == "file-1"
