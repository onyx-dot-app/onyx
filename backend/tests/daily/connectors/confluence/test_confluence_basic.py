import os
import time
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.confluence.connector import ConfluenceConnector
from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.models import Document


@pytest.fixture
def confluence_connector(space: str) -> ConfluenceConnector:
    connector = ConfluenceConnector(
        wiki_base=os.environ["CONFLUENCE_TEST_SPACE_URL"],
        space=space,
        is_cloud=os.environ.get("CONFLUENCE_IS_CLOUD", "true").lower() == "true",
        page_id=os.environ.get("CONFLUENCE_TEST_PAGE_ID", ""),
    )

    credentials_provider = OnyxStaticCredentialsProvider(
        None,
        DocumentSource.CONFLUENCE,
        {
            "confluence_username": os.environ["CONFLUENCE_USER_NAME"],
            "confluence_access_token": os.environ["CONFLUENCE_ACCESS_TOKEN"],
        },
    )
    connector.set_credentials_provider(credentials_provider)
    return connector


@pytest.mark.parametrize("space", [os.environ["CONFLUENCE_TEST_SPACE"]])
@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_confluence_connector_basic(
    mock_get_api_key: MagicMock, confluence_connector: ConfluenceConnector
) -> None:
    confluence_connector.set_allow_images(False)
    doc_batch_generator = confluence_connector.poll_source(0, time.time())

    doc_batch = next(doc_batch_generator)
    with pytest.raises(StopIteration):
        next(doc_batch_generator)

    assert len(doc_batch) == 2

    page_within_a_page_doc: Document | None = None
    page_doc: Document | None = None

    for doc in doc_batch:
        if doc.semantic_identifier == "DailyConnectorTestSpace Home":
            page_doc = doc
        elif doc.semantic_identifier == "Page Within A Page":
            page_within_a_page_doc = doc
        else:
            pass

    assert page_within_a_page_doc is not None
    assert page_within_a_page_doc.semantic_identifier == "Page Within A Page"
    assert page_within_a_page_doc.primary_owners
    assert page_within_a_page_doc.primary_owners[0].email == "hagen@danswer.ai"
    assert len(page_within_a_page_doc.sections) == 1

    page_within_a_page_section = page_within_a_page_doc.sections[0]
    page_within_a_page_text = "@Chris Weaver loves cherry pie"
    assert page_within_a_page_section.text == page_within_a_page_text
    assert (
        page_within_a_page_section.link
        == "https://danswerai.atlassian.net/wiki/spaces/DailyConne/pages/200769540/Page+Within+A+Page"
    )

    assert page_doc is not None
    assert page_doc.semantic_identifier == "DailyConnectorTestSpace Home"
    assert page_doc.metadata["labels"] == ["testlabel"]
    assert page_doc.primary_owners
    assert page_doc.primary_owners[0].email == "hagen@danswer.ai"
    assert len(page_doc.sections) == 2  # page text + attachment text

    page_section = page_doc.sections[0]
    assert page_section.text == "test123 " + page_within_a_page_text
    assert (
        page_section.link
        == "https://danswerai.atlassian.net/wiki/spaces/DailyConne/overview"
    )

    text_attachment_section = page_doc.sections[1]
    assert text_attachment_section.text == "small"
    assert text_attachment_section.link
    assert text_attachment_section.link.endswith("small-file.txt")


@pytest.mark.parametrize("space", ["MI"])
@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_confluence_connector_skip_images(
    mock_get_api_key: MagicMock, confluence_connector: ConfluenceConnector
) -> None:
    confluence_connector.set_allow_images(False)
    doc_batch_generator = confluence_connector.poll_source(0, time.time())

    doc_batch = next(doc_batch_generator)
    with pytest.raises(StopIteration):
        next(doc_batch_generator)

    assert len(doc_batch) == 8
    assert sum(len(doc.sections) for doc in doc_batch) == 8


@pytest.mark.parametrize("space", ["MI"])
@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_confluence_connector_allow_images(
    mock_get_api_key: MagicMock, confluence_connector: ConfluenceConnector
) -> None:
    confluence_connector.set_allow_images(True)

    doc_batch_generator = confluence_connector.poll_source(0, time.time())

    doc_batch = next(doc_batch_generator)
    with pytest.raises(StopIteration):
        next(doc_batch_generator)

    assert len(doc_batch) == 8
    assert sum(len(doc.sections) for doc in doc_batch) == 12
