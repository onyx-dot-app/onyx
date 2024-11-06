import os
import time
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from danswer.connectors.confluence.connector import ConfluenceConnector


@pytest.fixture
def confluence_connector() -> ConfluenceConnector:
    connector = ConfluenceConnector(
        wiki_base=os.environ["CONFLUENCE_TEST_SPACE_URL"],
        space=os.environ["CONFLUENCE_TEST_SPACE"],
        is_cloud=os.environ.get("CONFLUENCE_IS_CLOUD", "true").lower() == "true",
        page_id=os.environ.get("CONFLUENCE_TEST_PAGE_ID", ""),
    )

    connector.load_credentials(
        {
            "confluence_username": os.environ["CONFLUENCE_USER_NAME"],
            "confluence_access_token": os.environ["CONFLUENCE_ACCESS_TOKEN"],
        }
    )
    return connector


@patch(
    "danswer.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_confluence_connector_basic(
    mock_get_api_key: MagicMock, confluence_connector: ConfluenceConnector
) -> None:
    doc_batch_generator = confluence_connector.poll_source(0, time.time())

    doc_batch = next(doc_batch_generator)
    with pytest.raises(StopIteration):
        next(doc_batch_generator)

    assert len(doc_batch) == 2

    for doc in doc_batch:
        if doc.semantic_identifier == "DailyConnectorTestSpace Home":
            page_doc = doc
        elif ".txt" in doc.semantic_identifier:
            txt_doc = doc

    assert page_doc.semantic_identifier == "DailyConnectorTestSpace Home"
    assert page_doc.metadata["labels"] == ["testlabel"]
    assert page_doc.primary_owners
    assert page_doc.primary_owners[0].email == "chris@danswer.ai"
    assert len(page_doc.sections) == 1

    section = page_doc.sections[0]
    assert section.text == "test123"
    assert (
        section.link
        == "https://danswerai.atlassian.net/wiki/spaces/DailyConne/overview"
    )

    assert txt_doc.semantic_identifier == "small-file.txt"
    assert len(txt_doc.sections) == 1
    assert txt_doc.sections[0].text == "small"
    assert txt_doc.primary_owners
    assert txt_doc.primary_owners[0].email == "chris@danswer.ai"
    assert (
        txt_doc.sections[0].link
        == "https://danswerai.atlassian.net/wiki/pages/viewpageattachments.action?pageId=52494430&preview=%2F52494430%2F52527123%2Fsmall-file.txt"
    )
