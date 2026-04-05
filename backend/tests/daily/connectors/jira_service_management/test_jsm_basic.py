"""
Basic integration test for the Jira Service Management connector.

To run locally:
    export JSM_BASE_URL="https://yourcompany.atlassian.net"
    export JSM_PROJECT_KEY="IT"
    export JSM_USER_EMAIL="you@company.com"
    export JSM_API_TOKEN="your-token"

    pytest backend/tests/daily/connectors/jira_service_management/test_jsm_basic.py -v
"""

import os
import pytest

from onyx.connectors.jira_service_management.connector import JiraServiceManagementConnector


@pytest.fixture()
def jsm_connector() -> JiraServiceManagementConnector:
    base_url = os.environ["JSM_BASE_URL"]
    project_key = os.environ["JSM_PROJECT_KEY"]
    email = os.environ["JSM_USER_EMAIL"]
    api_token = os.environ["JSM_API_TOKEN"]

    connector = JiraServiceManagementConnector(
        jira_base_url=base_url,
        project_key=project_key,
    )
    connector.load_credentials(
        {"jira_user_email": email, "jira_api_token": api_token}
    )
    return connector


def test_jsm_connector_returns_documents(jsm_connector: JiraServiceManagementConnector) -> None:
    """Smoke test: connector should yield at least one document."""
    import time

    start = 0.0  # epoch beginning → fetch everything
    end = float(time.time())
    checkpoint = jsm_connector.build_dummy_checkpoint()

    docs_found = 0
    for output in jsm_connector.load_from_checkpoint(start, end, checkpoint):
        if isinstance(output, list):
            docs_found += len(output)
            if docs_found >= 5:
                break

    assert docs_found > 0, "No documents returned from JSM connector"


def test_jsm_document_fields(jsm_connector: JiraServiceManagementConnector) -> None:
    """Each document should have the required fields populated."""
    import time

    start = 0.0
    end = float(time.time())
    checkpoint = jsm_connector.build_dummy_checkpoint()

    for output in jsm_connector.load_from_checkpoint(start, end, checkpoint):
        if isinstance(output, list) and output:
            doc = output[0]
            assert doc.id.startswith("jsm:")
            assert doc.title
            assert doc.sections
            assert doc.sections[0].link.startswith("http")
            assert doc.metadata.get("issue_key")
            break
