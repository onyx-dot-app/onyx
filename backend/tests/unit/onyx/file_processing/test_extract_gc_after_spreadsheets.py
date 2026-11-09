"""Extraction collects garbage after every spreadsheet and otherwise at most
once per interval: openpyxl leaves cycles behind a workbook, and a collection
costs about a tenth of a second in a loaded worker."""

import io
from unittest.mock import patch

import pytest

from onyx.file_processing import extract_file_text
from onyx.file_processing.extract_file_text import (
    GC_COLLECT_INTERVAL_SECONDS,
    extract_text_and_images,
)

SPREADSHEET_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _extract(
    file_name: str, content_type: str | None, now: float, order: list[str]
) -> None:
    with (
        patch.object(
            extract_file_text,
            "_extract_text_and_images",
            side_effect=lambda *_args, **_kwargs: order.append("extract"),
        ),
        patch.object(extract_file_text, "time", monotonic=lambda: now),
        patch.object(
            extract_file_text.gc,
            "collect",
            side_effect=lambda: order.append("collect") or 0,
        ),
    ):
        extract_text_and_images(
            io.BytesIO(b"bytes"), file_name, content_type=content_type
        )


@pytest.fixture(autouse=True)
def _reset_last_collection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(extract_file_text, "_last_gc_collect_at", 0.0)


@pytest.mark.parametrize(
    ("file_name", "content_type"),
    [("sheet.xlsx", None), ("sheet.xlsm", None), ("renamed", SPREADSHEET_MIME)],
)
def test_every_spreadsheet_is_followed_by_a_collection(
    file_name: str, content_type: str | None
) -> None:
    order: list[str] = []
    _extract(file_name, content_type, now=100.0, order=order)
    _extract(file_name, content_type, now=101.0, order=order)

    # The collection must follow the extraction: it exists for the cycles the
    # workbook parser leaves behind.
    assert order == ["extract", "collect"] * 2


@pytest.mark.parametrize(
    ("file_name", "content_type"), [("notes.txt", "text/plain"), ("report.pdf", None)]
)
def test_other_files_collect_once_per_interval(
    file_name: str, content_type: str | None
) -> None:
    order: list[str] = []
    for offset in (0.0, GC_COLLECT_INTERVAL_SECONDS / 2, GC_COLLECT_INTERVAL_SECONDS):
        _extract(file_name, content_type, now=100.0 + offset, order=order)

    assert order == ["extract", "collect", "extract", "extract", "collect"]


def test_a_spreadsheet_collection_resets_the_interval() -> None:
    order: list[str] = []
    _extract("sheet.xlsx", None, now=100.0, order=order)
    _extract("report.pdf", None, now=101.0, order=order)

    assert order == ["extract", "collect", "extract"]
