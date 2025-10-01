import os
import time
from unittest.mock import patch

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.jira.connector import JiraConnector
from onyx.connectors.models import Document
from tests.daily.connectors.utils import load_all_docs_from_checkpoint_connector


def _make_connector(scoped_token: bool = False) -> JiraConnector:
    connector = JiraConnector(
        jira_base_url="https://danswerai.atlassian.net",
        project_key="AS",
        comment_email_blacklist=[],
        scoped_token=scoped_token,
    )
    connector.load_credentials(
        {
            "jira_user_email": os.environ["JIRA_USER_EMAIL"],
            "jira_api_token": (
                os.environ["JIRA_API_TOKEN_SCOPED"]
                if scoped_token
                else os.environ["JIRA_API_TOKEN"]
            ),
        }
    )
    return connector


@pytest.fixture
def jira_connector() -> JiraConnector:
    return _make_connector()


@pytest.fixture
def jira_connector_scoped() -> JiraConnector:
    return _make_connector(scoped_token=True)


@pytest.fixture
def jira_connector_with_jql() -> JiraConnector:
    connector = JiraConnector(
        jira_base_url="https://danswerai.atlassian.net",
        jql_query="project = 'AS' AND issuetype = Story",
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
def test_jira_connector_basic(reset: None, jira_connector: JiraConnector) -> None:
    _test_jira_connector_basic(jira_connector)


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_jira_connector_basic_scoped(
    reset: None, jira_connector_scoped: JiraConnector
) -> None:
    _test_jira_connector_basic(jira_connector_scoped)


def _test_jira_connector_basic(jira_connector: JiraConnector) -> None:
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
    assert story.semantic_identifier == "AS-3: Magic Answers"
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
        "updated": "2025-06-17T12:13:00.070-0700",
    }
    assert story.secondary_owners is None
    assert story.title == "AS-3 Magic Answers"
    assert story.from_ingestion_api is False
    assert story.additional_info is None

    assert len(story.sections) == 1
    section = story.sections[0]
    assert (
        section.text
        == "This is a critical request for super-human answer quality in Onyx! We need magic!\n"
    )
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


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_jira_connector_with_jql(
    reset: None, jira_connector_with_jql: JiraConnector
) -> None:
    """Test that JQL query functionality works correctly.

    This test verifies that when a JQL query is provided, only issues matching the query are returned.
    The JQL query used is "project = \'AS\' AND issuetype = Story", which should only return Story-type issues.
    """
    docs = load_all_docs_from_checkpoint_connector(
        connector=jira_connector_with_jql,
        start=0,
        end=time.time(),
    )

    # Should only return Story-type issues
    assert len(docs) == 1

    # All documents should be Story-type
    for doc in docs:
        assert doc.metadata["issuetype"] == "Story"

    # Verify it's the expected Story
    story = docs[0]
    assert story.id == "https://danswerai.atlassian.net/browse/AS-3"
    assert story.semantic_identifier == "AS-3: Magic Answers"
    assert story.metadata["issuetype"] == "Story"
