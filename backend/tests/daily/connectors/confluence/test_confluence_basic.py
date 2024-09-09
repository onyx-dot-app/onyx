import os
import time

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


def test_confluence_connector_basic(confluence_connector: ConfluenceConnector) -> None:
    doc_batch_generator = confluence_connector.poll_source(0, time.time())

    doc_batch = next(doc_batch_generator)
    with pytest.raises(StopIteration):
        next(doc_batch_generator)

    assert len(doc_batch) == 1

    doc = doc_batch[0]
    assert doc.semantic_identifier == "DailyConnectorTestSpace Home"
    assert doc.metadata["labels"] == ["testlabel"]
    assert doc.primary_owners
    assert doc.primary_owners[0].email == "chris@danswer.ai"
    assert len(doc.sections) == 1

    section = doc.sections[0]
    assert section.text == "test123small"
    assert (
        section.link
        == "https://danswerai.atlassian.net/wiki/spaces/DailyConne/overview"
    )
