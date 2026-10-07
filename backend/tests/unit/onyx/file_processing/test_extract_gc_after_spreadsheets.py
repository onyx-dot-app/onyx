"""Extraction collects garbage only after a spreadsheet: openpyxl leaves
cycles behind a workbook, and a collection after every other file costs about
a tenth of a second each in a loaded worker."""

import io
from unittest.mock import patch

import pytest

from onyx.file_processing.extract_file_text import extract_text_and_images


@pytest.mark.parametrize(
    ("file_name", "content_type", "collections"),
    [
        ("notes.txt", "text/plain", 0),
        ("report.pdf", None, 0),
        ("sheet.xlsx", None, 1),
        ("sheet.xlsm", None, 1),
        (
            "renamed",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            1,
        ),
    ],
)
def test_garbage_is_collected_after_spreadsheets_only(
    file_name: str, content_type: str | None, collections: int
) -> None:
    with (
        patch(
            "onyx.file_processing.extract_file_text._extract_text_and_images"
        ) as extract,
        patch("onyx.file_processing.extract_file_text.gc.collect") as collect,
    ):
        extract_text_and_images(
            io.BytesIO(b"bytes"), file_name, content_type=content_type
        )

    assert extract.call_count == 1
    assert collect.call_count == collections
