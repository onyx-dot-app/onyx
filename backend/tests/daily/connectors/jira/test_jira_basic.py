import os
import time

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.onyx_jira.connector import JiraConnector
from tests.daily.connectors.utils import load_all_docs_from_checkpoint_connector


@pytest.fixture
def jira_connector() -> JiraConnector:
    connector = JiraConnector(
        jira_base_url="https://danswerai.atlassian.net",
        project_key="AS",
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
    docs = load_all_docs_from_checkpoint_connector(
        connector=jira_connector,
        start=0,
        end=time.time(),
    )
    assert len(docs) == 1
    doc = docs[0]

    assert doc.id == "https://danswerai.atlassian.net/browse/AS-2"
    assert doc.semantic_identifier == "AS-2: test123small"
    assert doc.source == DocumentSource.JIRA
    assert doc.metadata == {"priority": "Medium", "status": "Backlog"}
    assert doc.secondary_owners is None
    assert doc.title == "AS-2 test123small"
    assert doc.from_ingestion_api is False
    assert doc.additional_info is None

    assert len(doc.sections) == 1
    section = doc.sections[0]
    assert section.text == "example_text\n"
    assert section.link == "https://danswerai.atlassian.net/browse/AS-2"
