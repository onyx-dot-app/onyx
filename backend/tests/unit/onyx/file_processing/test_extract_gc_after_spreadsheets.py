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
    order: list[str] = []
    with (
        patch(
            "onyx.file_processing.extract_file_text._extract_text_and_images",
            side_effect=lambda *_args, **_kwargs: order.append("extract"),
        ),
        patch(
            "onyx.file_processing.extract_file_text.gc.collect",
            side_effect=lambda: order.append("collect") or 0,
        ),
    ):
        extract_text_and_images(
            io.BytesIO(b"bytes"), file_name, content_type=content_type
        )

    # The collection must follow the extraction: it exists for the cycles the
    # workbook parser leaves behind.
    assert order == ["extract"] + ["collect"] * collections
