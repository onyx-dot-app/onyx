"""Basic integration tests for Jira Service Management connector.

Setup instructions:
1. Create or access a Jira instance with JSM enabled
2. Create a JSM project (Service Management type) with some test tickets
3. Generate an API token from your Atlassian account
4. Add the following secrets to your test environment:
   - JIRA_USER_EMAIL: Your Atlassian account email
   - JIRA_API_TOKEN: Your API token
   - JIRA_JSM_PROJECT_KEY: The key of your test JSM project (e.g., "SUPPORT")
   - JIRA_BASE_URL: Your Jira instance URL (e.g., "https://your-domain.atlassian.net")
"""

import time
from unittest.mock import patch

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)
from tests.daily.connectors.utils import load_all_from_connector
from tests.utils.secret_names import TestSecret

pytestmark = pytest.mark.secrets(
    TestSecret.JIRA_USER_EMAIL,
    TestSecret.JIRA_API_TOKEN,
)


@pytest.fixture
def jsm_connector(
    test_secrets: dict[TestSecret, str],
) -> JiraServiceManagementConnector:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://danswerai.atlassian.net",
        project_key="AS",
        comment_email_blacklist=[],
    )
    connector.load_credentials(
        {
            "jira_user_email": test_secrets[TestSecret.JIRA_USER_EMAIL],
            "jira_api_token": test_secrets[TestSecret.JIRA_API_TOKEN],
        }
    )
    return connector


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_jsm_connector_basic(
    reset: None,  # noqa: ARG001
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    """Test basic JSM connector functionality: load and validate documents."""
    output = load_all_from_connector(
        connector=jsm_connector,
        start=0,
        end=time.time(),
    )
    docs = output.documents

    assert len(docs) > 0, "JSM connector should retrieve at least one document"

    for doc in docs:
        assert (
            doc.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
        ), "Document source should be JIRA_SERVICE_MANAGEMENT"
        assert doc.id, "Document must have an ID"
        assert doc.semantic_identifier, "Document must have a semantic identifier"
        assert doc.sections, "Document must have at least one section"

        assert any(
            section.text.strip() for section in doc.sections
        ), "Document must have non-empty text content"


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_jsm_connector_with_jql(
    reset: None,  # noqa: ARG001
    test_secrets: dict[TestSecret, str],
) -> None:
    """Test JSM connector with custom JQL query."""
    connector = JiraServiceManagementConnector(
        jira_base_url="https://danswerai.atlassian.net",
        jql_query="project = 'AS' AND issuetype = Story",
        comment_email_blacklist=[],
    )
    connector.load_credentials(
        {
            "jira_user_email": test_secrets[TestSecret.JIRA_USER_EMAIL],
            "jira_api_token": test_secrets[TestSecret.JIRA_API_TOKEN],
        }
    )
    connector.validate_connector_settings()

    output = load_all_from_connector(
        connector=connector,
        start=0,
        end=time.time(),
    )
    docs = output.documents

    assert len(docs) > 0, "JSM connector with JQL should retrieve documents"

    for doc in docs:
        assert (
            doc.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
        ), "Document source should be JIRA_SERVICE_MANAGEMENT"
