import os
import time

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)


@pytest.fixture
def jsm_connector() -> JiraServiceManagementConnector:
    base_url = os.environ.get("JSM_BASE_URL", "https://onyx-test.atlassian.net")
    project_key = os.environ.get("JSM_PROJECT_KEY", "ITSM")
    connector = JiraServiceManagementConnector(
        base_url=base_url,
        project_key=project_key,
    )
    connector.load_credentials(
        {
            "jira_user_email": os.environ["JSM_USER_EMAIL"],
            "jira_api_token": os.environ["JSM_API_TOKEN"],
        }
    )
    return connector


@pytest.mark.xfail(
    reason="Requires live Jira Service Management credentials in environment"
)
def test_jira_service_management_connector_basic(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    doc_batches = list(jsm_connector.load_from_state())
    docs = [doc for batch in doc_batches for doc in batch]
    assert len(docs) > 0
    for doc in docs:
        assert doc.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
        assert doc.id.startswith("JSM_")

    now = time.time()
    poll_batches = list(jsm_connector.poll_source(0.0, now))
    polled_docs = [doc for batch in poll_batches for doc in batch]
    assert len(polled_docs) == len(docs)
