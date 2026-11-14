from unittest.mock import MagicMock, patch

import pytest

from onyx.connectors.highspot.connector import HighspotConnector


@pytest.mark.parametrize(
    ("content_name", "downloaded"),
    [
        ("deck.PPTX", True),
        ("notes.md", True),
        ("photo.png", False),
        ("archive.zip", False),
        ("README", False),
    ],
)
def test_item_content_downloads_only_indexable_files(
    content_name: str, downloaded: bool
) -> None:
    connector = HighspotConnector()
    client = MagicMock()
    client.get_item_content.return_value = b"body"
    connector._client = client
    item = {
        "id": "item-1",
        "content_name": content_name,
        "can_download": True,
        "content_type": "File",
        "title": "Title",
        "description": "",
    }
    with patch(
        "onyx.connectors.highspot.connector.extract_file_text",
        return_value="extracted",
    ):
        content = connector._get_item_content(item)

    assert client.get_item_content.called is downloaded
    assert (content == "extracted") is downloaded
