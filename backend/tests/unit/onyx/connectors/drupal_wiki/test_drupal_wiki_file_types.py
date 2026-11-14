import pytest

from onyx.connectors.drupal_wiki.connector import DrupalWikiConnector


@pytest.mark.parametrize(
    ("file_name", "expected"),
    [
        ("report.pdf", True),
        ("table.csv", True),
        # Images pass here. allow_images is applied after the download.
        ("photo.png", True),
        ("archive.zip", False),
        ("", False),
    ],
)
def test_validate_attachment_filetype(file_name: str, expected: bool) -> None:
    connector = DrupalWikiConnector(base_url="https://wiki.example.com")
    assert connector._validate_attachment_filetype({"fileName": file_name}) is expected
