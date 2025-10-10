import os
import time
from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.confluence.connector import ConfluenceConnector
from onyx.connectors.confluence.utils import AttachmentProcessingResult
from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.models import Document
from tests.daily.connectors.utils import load_all_docs_from_checkpoint_connector


def _make_connector(
    space: str, access_token: str, scoped_token: bool = False
) -> ConfluenceConnector:
    connector = ConfluenceConnector(
        wiki_base=os.environ["CONFLUENCE_TEST_SPACE_URL"],
        space=space,
        is_cloud=os.environ.get("CONFLUENCE_IS_CLOUD", "true").lower() == "true",
        page_id=os.environ.get("CONFLUENCE_TEST_PAGE_ID", ""),
        scoped_token=scoped_token,
    )

    credentials_provider = OnyxStaticCredentialsProvider(
        None,
        DocumentSource.CONFLUENCE,
        {
            "confluence_username": os.environ["CONFLUENCE_USER_NAME"],
            "confluence_access_token": access_token,
        },
    )
    connector.set_credentials_provider(credentials_provider)
    return connector


@pytest.fixture
def confluence_connector(space: str) -> ConfluenceConnector:
    return _make_connector(space, os.environ["CONFLUENCE_ACCESS_TOKEN"].strip())


@pytest.fixture
def confluence_connector_scoped(space: str) -> ConfluenceConnector:
    return _make_connector(
        space, os.environ["CONFLUENCE_ACCESS_TOKEN_SCOPED"].strip(), scoped_token=True
    )


@pytest.mark.parametrize("space", [os.getenv("CONFLUENCE_TEST_SPACE") or "DailyConne"])
@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_confluence_connector_basic(
    mock_get_api_key: MagicMock, confluence_connector: ConfluenceConnector
) -> None:
    _test_confluence_connector_basic(confluence_connector)


@pytest.mark.parametrize("space", [os.getenv("CONFLUENCE_TEST_SPACE") or "DailyConne"])
@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_confluence_connector_basic_scoped(
    mock_get_api_key: MagicMock, confluence_connector_scoped: ConfluenceConnector
) -> None:
    _test_confluence_connector_basic(
        confluence_connector_scoped, expect_attachments=True
    )


def _test_confluence_connector_basic(
    confluence_connector: ConfluenceConnector, expect_attachments: bool = True
) -> None:
    confluence_connector.set_allow_images(False)
    doc_batch = load_all_docs_from_checkpoint_connector(
        confluence_connector, 0, time.time()
    )

    assert len(doc_batch) == (3 if expect_attachments else 2)

    page_within_a_page_doc: Document | None = None
    page_doc: Document | None = None
    small_file_doc: Document | None = None

    for doc in doc_batch:
        if doc.semantic_identifier == "DailyConnectorTestSpace Home":
            page_doc = doc
        elif doc.semantic_identifier == "Page Within A Page":
            page_within_a_page_doc = doc
        elif doc.semantic_identifier == "small-file.txt":
            small_file_doc = doc
        else:
            print(f"Unexpected doc: {doc.semantic_identifier}")

    assert page_within_a_page_doc is not None
    assert page_within_a_page_doc.semantic_identifier == "Page Within A Page"
    assert page_within_a_page_doc.primary_owners
    assert page_within_a_page_doc.primary_owners[0].email == "hagen@danswer.ai"
    assert (
        page_within_a_page_doc.id
        == "https://danswerai.atlassian.net/wiki/spaces/DailyConne/pages/200769540/Page+Within+A+Page"
    )
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
    assert (
        page_doc.id == "https://danswerai.atlassian.net/wiki/spaces/DailyConne/overview"
    )
    assert page_doc.metadata["labels"] == ["testlabel"]
    assert page_doc.primary_owners
    assert page_doc.primary_owners[0].email == "hagen@danswer.ai"
    assert (
        len(page_doc.sections) == 1
    )  # just page text, attachment text is separate doc

    page_section = page_doc.sections[0]
    assert (
        page_section.text
        == "test123 "
        + page_within_a_page_text
        + "\n<attachment>small-file.txt</attachment>\n<attachment>big-file.txt</attachment>"
    )
    assert (
        page_section.link
        == "https://danswerai.atlassian.net/wiki/spaces/DailyConne/overview"
    )

    if expect_attachments:
        assert small_file_doc is not None
        text_attachment_section = small_file_doc.sections[0]
        assert text_attachment_section.text == "small"
        assert text_attachment_section.link
        assert text_attachment_section.link.split("?")[0].endswith("small-file.txt")


@pytest.mark.parametrize("space", ["MI"])
@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_confluence_connector_skip_images(
    mock_get_api_key: MagicMock, confluence_connector: ConfluenceConnector
) -> None:
    confluence_connector.set_allow_images(False)
    doc_batch = load_all_docs_from_checkpoint_connector(
        confluence_connector, 0, time.time()
    )

    assert len(doc_batch) == 8
    assert sum(len(doc.sections) for doc in doc_batch) == 8


def mock_process_image_attachment(
    *args: Any, **kwargs: Any
) -> AttachmentProcessingResult:
    """We need this mock to bypass DB access happening in the connector. Which shouldn't
    be done as a rule to begin with, but life is not perfect. Fix it later"""

    return AttachmentProcessingResult(
        text="Hi_text",
        file_name="Hi_filename",
        error=None,
    )


@pytest.mark.parametrize("space", ["MI"])
@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
@patch(
    "onyx.connectors.confluence.utils._process_image_attachment",
    side_effect=mock_process_image_attachment,
)
def test_confluence_connector_allow_images(
    mock_get_api_key: MagicMock,
    mock_process_image_attachment: MagicMock,
    confluence_connector: ConfluenceConnector,
) -> None:
    confluence_connector.set_allow_images(True)

    doc_batch = load_all_docs_from_checkpoint_connector(
        confluence_connector, 0, time.time()
    )

    assert len(doc_batch) == 12
    assert sum(len(doc.sections) for doc in doc_batch) == 12
