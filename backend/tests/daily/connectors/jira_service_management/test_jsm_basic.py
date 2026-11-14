"""Daily live test for the Jira Service Management connector.

Setup guide (also in the PR description): create a JSM Cloud site with one
IT service-management project, key `IT`, containing one customer request
`IT-1` of request type `Get IT help`, raised by the connector account. Give
the connector account's API token access to the site (scoped tokens need
`read:servicedesk-request` in addition to the Jira scopes).
"""

import time
from unittest.mock import patch

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)
from onyx.connectors.models import Document
from tests.daily.connectors.utils import load_all_from_connector
from tests.utils.secret_names import TestSecret

pytestmark = pytest.mark.secrets(
    TestSecret.JIRA_USER_EMAIL,
    TestSecret.JIRA_API_TOKEN,
)

JSM_BASE_URL = "https://danswerai.atlassian.net"
JSM_PROJECT_KEY = "IT"


@pytest.fixture
def jsm_connector(
    test_secrets: dict[TestSecret, str],
) -> JiraServiceManagementConnector:
    """Instantiate and validate a JSM connector for daily live tests."""
    connector = JiraServiceManagementConnector(
        jira_base_url=JSM_BASE_URL,
        project_key=JSM_PROJECT_KEY,
        comment_email_blacklist=[],
    )
    connector.load_credentials(
        {
            "jira_user_email": test_secrets[TestSecret.JIRA_USER_EMAIL],
            "jira_api_token": test_secrets[TestSecret.JIRA_API_TOKEN],
        }
    )
    connector.validate_connector_settings()
    return connector


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_jsm_connector_basic(
    reset: None,  # noqa: ARG001
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    """Verify end-to-end JSM ticket indexing and portal enrichment."""
    docs = load_all_from_connector(
        connector=jsm_connector,
        start=0,
        end=time.time(),
    ).documents

    assert len(docs) >= 1

    ticket: Document | None = None
    for doc in docs:
        if doc.metadata.get("key") == "IT-1":
            ticket = doc
            break

    assert ticket is not None
    assert ticket.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
    assert ticket.id == f"{JSM_BASE_URL}/browse/IT-1"
    assert ticket.semantic_identifier.startswith("IT-1:")

    # Jira fields still index as with the plain Jira connector.
    assert ticket.metadata["project"] == JSM_PROJECT_KEY
    assert "status" in ticket.metadata

    # JSM portal enrichment from the Service Desk API.
    assert ticket.metadata.get("request_type") == "Get IT help"
    assert "portal_status" in ticket.metadata
