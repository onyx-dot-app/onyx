import os
import time
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import Document
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


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_jira_connector_basic(
    mock_get_api_key: MagicMock, jira_connector: JiraConnector
) -> None:
    docs = load_all_docs_from_checkpoint_connector(
        connector=jira_connector,
        start=0,
        end=time.time(),
    )
    assert len(docs) == 2

    # Find story and epic
    story: Document | None = None
    epic: Document | None = None
    for doc in docs:
        if doc.metadata["issuetype"] == "Story":
            story = doc
        elif doc.metadata["issuetype"] == "Epic":
            epic = doc

    assert story is not None
    assert epic is not None

    # Check task
    assert story.id == "https://danswerai.atlassian.net/browse/AS-3"
    assert story.semantic_identifier == "AS-3: test123small"
    assert story.source == DocumentSource.JIRA
    assert story.metadata == {
        "priority": "Medium",
        "status": "Done",
        "resolution": "Done",
        "resolution_date": "2025-05-29T15:33:31.031-0700",
        "reporter": "Chris Weaver",
        "assignee": "Chris Weaver",
        "issuetype": "Story",
        "created": "2025-04-16T16:44:06.716-0700",
        "reporter_email": "chris@onyx.app",
        "assignee_email": "chris@onyx.app",
        "project_name": "DailyConnectorTestProject",
        "project": "AS",
        "parent": "AS-4",
        "key": "AS-3",
        "updated": "2025-05-29T15:33:31.085-0700",
    }
    assert story.secondary_owners is None
    assert story.title == "AS-3 test123small"
    assert story.from_ingestion_api is False
    assert story.additional_info is None

    assert len(story.sections) == 1
    section = story.sections[0]
    assert section.text == "example_text\n"
    assert section.link == "https://danswerai.atlassian.net/browse/AS-3"

    # Check epic
    assert epic.id == "https://danswerai.atlassian.net/browse/AS-4"
    assert epic.semantic_identifier == "AS-4: EPIC"
    assert epic.source == DocumentSource.JIRA
    assert epic.metadata == {
        "priority": "Medium",
        "status": "Backlog",
        "reporter": "Founder Onyx",
        "assignee": "Chris Weaver",
        "issuetype": "Epic",
        "created": "2025-04-16T16:55:53.068-0700",
        "reporter_email": "founders@onyx.app",
        "assignee_email": "chris@onyx.app",
        "project_name": "DailyConnectorTestProject",
        "project": "AS",
        "key": "AS-4",
        "updated": "2025-05-29T14:43:05.312-0700",
    }
    assert epic.secondary_owners is None
    assert epic.title == "AS-4 EPIC"
    assert epic.from_ingestion_api is False
    assert epic.additional_info is None

    assert len(epic.sections) == 1
    section = epic.sections[0]
    assert section.text == "example_text\n"
    assert section.link == "https://danswerai.atlassian.net/browse/AS-4"
