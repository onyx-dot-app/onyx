import os
import time
from unittest.mock import patch

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.jira_service_management.connector import JiraServiceManagementConnector
from onyx.connectors.models import Document
from tests.daily.connectors.utils import load_all_docs_from_checkpoint_connector


def _make_connector(scoped_token: bool = False) -> JiraServiceManagementConnector:
    connector = JiraServiceManagementConnector(
        jira_service_management_base_url="https://danswerai.atlassian.net",
        project_key="AS",
        comment_email_blacklist=[],
        # JSM might not support scoped_token yet, or uses the same logic. 
        # Keeping it compatible with the base class logic if it exists.
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
def jsm_connector() -> JiraServiceManagementConnector:
    return _make_connector()


@pytest.fixture
def jsm_connector_scoped() -> JiraServiceManagementConnector:
    return _make_connector(scoped_token=True)


@pytest.fixture
def jsm_connector_with_jql() -> JiraServiceManagementConnector:
    connector = JiraServiceManagementConnector(
        jira_service_management_base_url="https://danswerai.atlassian.net",
        jql_query="project = 'AS' AND issuetype = Story",
        comment_email_blacklist=[],
    )
    connector.load_credentials(
        {
            "jira_user_email": os.environ["JIRA_USER_EMAIL"],
            "jira_api_token": os.environ["JIRA_API_TOKEN"],
        }
    )
    connector.validate_connector_settings()

    return connector


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_jsm_connector_basic(reset: None, jsm_connector: JiraServiceManagementConnector) -> None:
    _test_jsm_connector_basic(jsm_connector)


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_jsm_connector_basic_scoped(
    reset: None, jsm_connector_scoped: JiraServiceManagementConnector
) -> None:
    _test_jsm_connector_basic(jsm_connector_scoped)


def _test_jsm_connector_basic(jsm_connector: JiraServiceManagementConnector) -> None:
    docs = load_all_docs_from_checkpoint_connector(
        connector=jsm_connector,
        start=0,
        end=time.time(),
    )
    # Adjust this based on what real JSM data returns, but for now we expect similar docs
    assert len(docs) >= 1

    # Find story
    story: Document | None = None
    for doc in docs:
        if doc.metadata.get("issuetype") == "Story":
            story = doc
            break

    assert story is not None

    # Check source type - THIS IS THE CRITICAL ASSERTION
    assert story.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
    
    # Basic metadata checks
    assert story.metadata["project"] == "AS"
    assert story.metadata["issuetype"] == "Story"
    assert story.from_ingestion_api is False


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_jsm_connector_with_jql(
    reset: None, jsm_connector_with_jql: JiraServiceManagementConnector
) -> None:
    """Test that JQL query functionality works correctly."""
    docs = load_all_docs_from_checkpoint_connector(
        connector=jsm_connector_with_jql,
        start=0,
        end=time.time(),
    )

    # Should only return Story-type issues
    assert len(docs) >= 1

    # All documents should be Story-type
    for doc in docs:
        assert doc.metadata["issuetype"] == "Story"
        assert doc.source == DocumentSource.JIRA_SERVICE_MANAGEMENT