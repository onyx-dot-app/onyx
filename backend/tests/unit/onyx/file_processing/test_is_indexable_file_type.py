import pytest

from onyx.file_processing.file_types import is_indexable_file_type


@pytest.mark.parametrize(
    ("file_name", "mime_type", "allow_images", "expected"),
    [
        # Text and documents are read by extension.
        ("notes.md", "text/markdown", False, True),
        ("report.PDF", None, False, True),
        ("table.csv", "text/csv", False, True),
        ("book.xlsm", None, False, True),
        ("deck.pptx", "application/octet-stream", False, True),
        # No supported extension: the mime type alone is not enough.
        ("README", "text/markdown", False, False),
        ("archive.zip", "application/zip", True, False),
        ("binary", None, True, False),
        # Images need allow_images, by mime type or by extension.
        ("photo.png", "image/png", False, False),
        ("photo.png", "image/png", True, True),
        ("photo", "image/jpeg; charset=binary", True, True),
        ("photo.webp", None, True, True),
        ("photo.webp", None, False, False),
        # An image type that Onyx does not read.
        ("anim.gif", "image/gif", True, False),
    ],
)
def test_is_indexable_file_type(
    file_name: str, mime_type: str | None, allow_images: bool, expected: bool
) -> None:
    assert is_indexable_file_type(file_name, mime_type, allow_images) is expected
