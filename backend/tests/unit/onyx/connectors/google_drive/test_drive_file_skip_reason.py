"""The Drive metadata check against the conversion handler table."""

from typing import Any

import pytest

from onyx.connectors.google_drive.constants import (
    DRIVE_FOLDER_TYPE,
    DRIVE_SHORTCUT_TYPE,
)
from onyx.connectors.google_drive.doc_conversion import (
    _MIME_HANDLERS,
    drive_file_skip_reason,
)
from onyx.connectors.google_drive.models import GDriveMimeType

_THRESHOLD = 100


def _skip_reason(
    file: dict[str, Any],
    *,
    allow_images: bool = True,
    has_raw_file_callback: bool = True,
    exclude_domain_link_only: bool = False,
) -> str | None:
    return drive_file_skip_reason(
        file,
        allow_images=allow_images,
        size_threshold=_THRESHOLD,
        has_raw_file_callback=has_raw_file_callback,
        exclude_domain_link_only=exclude_domain_link_only,
    )


@pytest.mark.parametrize("mime_type", sorted(_MIME_HANDLERS))
def test_every_handled_mime_type_is_accepted(mime_type: str) -> None:
    # No extension, so only the mime type can accept the file.
    assert _skip_reason({"mimeType": mime_type, "name": "file"}) is None


def test_the_table_has_the_drive_native_types() -> None:
    for mime_type in (
        GDriveMimeType.DOC,
        GDriveMimeType.SPREADSHEET,
        GDriveMimeType.PPT,
        GDriveMimeType.FORM,
    ):
        assert mime_type.value in _MIME_HANDLERS


@pytest.mark.parametrize(
    "file",
    [
        {"mimeType": "application/zip", "name": "a.zip"},
        {"mimeType": "application/octet-stream", "name": "a.bin"},
        {"mimeType": "text/markdown", "name": "README"},
        # Drive can download no Google type and cannot export a Drawing.
        {"mimeType": "application/vnd.google-apps.drawing", "name": "d.pdf"},
        {"mimeType": "image/gif", "name": "a.gif"},
    ],
)
def test_unsupported_types_are_rejected(file: dict[str, str]) -> None:
    assert _skip_reason(file) is not None


def test_an_unknown_mime_type_is_read_by_extension() -> None:
    assert (
        _skip_reason({"mimeType": "application/octet-stream", "name": "a.md"}) is None
    )


@pytest.mark.parametrize("mime_type", [DRIVE_SHORTCUT_TYPE, DRIVE_FOLDER_TYPE])
def test_shortcuts_and_folders_are_rejected(mime_type: str) -> None:
    assert _skip_reason({"mimeType": mime_type, "name": "x"}) is not None


def test_size_threshold() -> None:
    pdf = {"mimeType": GDriveMimeType.PDF.value, "name": "a.pdf"}
    assert _skip_reason({**pdf, "size": str(_THRESHOLD)}) is None
    assert _skip_reason({**pdf, "size": str(_THRESHOLD + 1)}) is not None
    # A native Google file lists no size.
    assert _skip_reason({"mimeType": GDriveMimeType.DOC.value, "name": "d"}) is None


@pytest.mark.parametrize(
    "file",
    [
        {"mimeType": "image/png", "name": "a.png"},
        # An image read by its extension.
        {"mimeType": "application/octet-stream", "name": "a.jpg"},
    ],
)
def test_images_need_allow_images(file: dict[str, str]) -> None:
    assert _skip_reason(file, allow_images=True) is None
    assert _skip_reason(file, allow_images=False) is not None


@pytest.mark.parametrize(
    "file",
    [
        {"mimeType": GDriveMimeType.SPREADSHEET.value, "name": "sheet"},
        {"mimeType": GDriveMimeType.SPREADSHEET_OPEN_FORMAT.value, "name": "book"},
        {"mimeType": "text/csv", "name": "table.csv"},
        {"mimeType": "application/octet-stream", "name": "table.tsv"},
    ],
)
def test_tabular_files_need_a_raw_file_callback(file: dict[str, str]) -> None:
    assert _skip_reason(file, has_raw_file_callback=True) is None
    assert _skip_reason(file, has_raw_file_callback=False) is not None


def test_non_tabular_files_do_not_need_a_raw_file_callback() -> None:
    doc = {"mimeType": GDriveMimeType.DOC.value, "name": "d"}
    assert _skip_reason(doc, has_raw_file_callback=False) is None


def test_link_only_files_are_rejected_only_when_excluded() -> None:
    file = {
        "mimeType": GDriveMimeType.DOC.value,
        "name": "d",
        "permissions": [{"type": "domain", "allowFileDiscovery": False}],
    }
    assert _skip_reason(file, exclude_domain_link_only=False) is None
    assert _skip_reason(file, exclude_domain_link_only=True) is not None
