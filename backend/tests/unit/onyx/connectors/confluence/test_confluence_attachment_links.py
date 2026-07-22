"""Confluence attachment links retain their platform-specific canonical form."""

from unittest import mock

import pytest

from onyx.connectors.confluence.connector import ConfluenceConnector
from onyx.connectors.confluence.onyx_confluence import OnyxConfluence
from onyx.connectors.models import Document

_PAGE_ID = "111"
_ATTACHMENT_PAGE_ID = "222"
_ATTACHMENT_TITLE = "project overview.pptx"
_ENCODED_ATTACHMENT_TITLE = "project%20overview.pptx"

_PAGE = {
    "id": _PAGE_ID,
    "title": "Parent page",
    "_links": {"webui": f"/pages/viewpage.action?pageId={_PAGE_ID}"},
}
_ATTACHMENT = {
    "id": "att123",
    "title": _ATTACHMENT_TITLE,
    "metadata": {
        "mediaType": "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    },
    "_links": {
        "download": (
            f"/download/attachments/{_ATTACHMENT_PAGE_ID}/{_ENCODED_ATTACHMENT_TITLE}"
        ),
        "webui": (
            "/pages/viewpageattachments.action"
            f"?pageId={_ATTACHMENT_PAGE_ID}&preview=att123"
        ),
    },
    "history": {"createdDate": "2018-01-01T00:00:00.000+0000"},
}


@pytest.mark.parametrize(
    ("is_cloud", "wiki_base", "expected_link"),
    [
        (
            False,
            "https://wiki.example.com",
            (
                f"https://wiki.example.com/download/attachments/{_ATTACHMENT_PAGE_ID}/"
                f"{_ENCODED_ATTACHMENT_TITLE}"
            ),
        ),
        (
            True,
            "https://example.atlassian.net/wiki",
            (
                f"https://example.atlassian.net/wiki/download/attachments/{_PAGE_ID}/"
                f"{_ENCODED_ATTACHMENT_TITLE}"
            ),
        ),
    ],
)
def test_attachment_section_link_uses_platform_specific_url(
    is_cloud: bool,
    wiki_base: str,
    expected_link: str,
) -> None:
    connector = ConfluenceConnector(wiki_base=wiki_base, is_cloud=is_cloud)
    confluence_client = mock.Mock(spec=OnyxConfluence)
    confluence_client.paginated_cql_retrieval.return_value = iter([_ATTACHMENT])

    with (
        mock.patch.object(
            ConfluenceConnector,
            "confluence_client",
            new_callable=mock.PropertyMock,
            return_value=confluence_client,
        ),
        mock.patch(
            "onyx.connectors.confluence.connector.convert_attachment_to_content",
            return_value=("attachment content", None),
        ),
        mock.patch.object(
            connector, "_maybe_yield_page_hierarchy_node", return_value=None
        ),
    ):
        documents, failures = connector._fetch_page_attachments(_PAGE)

    assert failures == []
    assert len(documents) == 1
    attachment_document = documents[0]
    assert isinstance(attachment_document, Document)
    assert attachment_document.sections[0].link == expected_link
