import pytest

from onyx.connectors.confluence.utils import validate_attachment_filetype


@pytest.mark.parametrize(
    ("title", "media_type", "expected"),
    [
        # A supported image media type wins over the title.
        ("diagram", "image/png", True),
        # An image media type that Onyx does not read wins over the title.
        ("anim.png", "image/gif", False),
        # Any other media type: the title extension decides.
        ("report.pdf", "application/pdf", True),
        ("photo.jpg", "application/octet-stream", True),
        ("archive.zip", "application/zip", False),
        ("notes", "text/plain", False),
    ],
)
def test_validate_attachment_filetype(
    title: str, media_type: str, expected: bool
) -> None:
    attachment = {"title": title, "metadata": {"mediaType": media_type}}
    assert validate_attachment_filetype(attachment) is expected
