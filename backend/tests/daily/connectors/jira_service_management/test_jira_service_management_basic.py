"""Daily test for the Jira Service Management connector.

Environment setup for maintainers: point the connector at a Jira Cloud site
with JSM enabled and one service-desk project whose key is exported as
``JSM_PROJECT_KEY`` (defaults to ``SD``). The project should contain at
least one customer-visible portal request so the Service Desk metadata
(``service_desk_status``, ``customer_portal_link``) is exercised. The same
``jira-user-email`` / ``jira-api-token`` secrets the Jira daily test uses
are required; the token needs the ``read:servicedesk-request`` scope for
the enrichment call, though indexing still works without it.
"""

import os
import time

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

JSM_BASE_URL = "https://danswerai.atlassian.net"
JSM_PROJECT_KEY = os.environ.get("JSM_PROJECT_KEY", "SD")


@pytest.fixture
def jsm_connector(
    test_secrets: dict[TestSecret, str],
) -> JiraServiceManagementConnector:
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


def test_jsm_connector_scopes_to_service_desk(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    jql = jsm_connector._get_jql_query(0, int(time.time()))
    assert "projectType = service_desk" in jql
    assert f'project = "{JSM_PROJECT_KEY}"' in jql


def test_jsm_connector_loads_requests(
    reset: None,  # noqa: ARG001
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    output = load_all_from_connector(
        connector=jsm_connector,
        start=0,
        end=time.time(),
    )

    assert output.documents
    for doc in output.documents:
        assert doc.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
        assert doc.metadata["project"] == JSM_PROJECT_KEY

    # At least one doc should be a portal request carrying JSM metadata.
    assert any("service_desk_status" in doc.metadata for doc in output.documents), (
        "expected at least one portal request with service-desk status"
    )
