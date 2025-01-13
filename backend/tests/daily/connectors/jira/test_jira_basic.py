import os
import time

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.onyx_jira.connector import JiraConnector


@pytest.fixture
def jira_connector() -> JiraConnector:
    connector = JiraConnector(
        "https://danswerai.atlassian.net/jira/software/c/projects/AS/boards/6",
        comment_email_blacklist=[],
    )
    connector.load_credentials(
        {
            "jira_user_email": os.environ["JIRA_USER_EMAIL"],
            "jira_api_token": os.environ["JIRA_API_TOKEN"],
        }
    )
    return connector


def test_jira_connector_basic(jira_connector: JiraConnector) -> None:
    doc_batch_generator = jira_connector.poll_source(0, time.time())

    doc_batch = next(doc_batch_generator)
    with pytest.raises(StopIteration):
        next(doc_batch_generator)

    assert len(doc_batch) == 1

    doc = doc_batch[0]

    assert doc.id == "https://danswerai.atlassian.net/browse/AS-2"
    assert doc.semantic_identifier == "test123small"
    assert doc.source == DocumentSource.JIRA
    assert doc.metadata == {"priority": "Medium", "status": "Backlog"}
    assert doc.secondary_owners is None
    assert doc.title is None
    assert doc.from_ingestion_api is False
    assert doc.additional_info is None

    assert len(doc.sections) == 1
    section = doc.sections[0]
    assert section.text == "example_text\n"
    assert section.link == "https://danswerai.atlassian.net/browse/AS-2"
