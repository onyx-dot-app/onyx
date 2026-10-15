import os
import time

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)
from onyx.connectors.models import Document, HierarchyNode


@pytest.fixture
def jsm_connector() -> JiraServiceManagementConnector:
    base_url = os.environ.get("JIRA_SERVICE_MANAGEMENT_BASE_URL")
    user_email = os.environ.get("JIRA_SERVICE_MANAGEMENT_USER_EMAIL")
    api_token = os.environ.get("JIRA_SERVICE_MANAGEMENT_API_TOKEN")
    project_key = os.environ.get("JIRA_SERVICE_MANAGEMENT_PROJECT_KEY")

    if not base_url or not api_token:
        pytest.skip(
            "JIRA_SERVICE_MANAGEMENT_BASE_URL and JIRA_SERVICE_MANAGEMENT_API_TOKEN required for live JSM test"
        )

    connector = JiraServiceManagementConnector(
        jira_service_management_base_url=base_url,
        project_key=project_key,
    )
    connector.load_credentials(
        {
            "jira_user_email": user_email,
            "jira_api_token": api_token,
        }
    )
    return connector


def test_jira_service_management_connector_basic(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    jsm_connector.validate_connector_settings()

    docs: list[Document] = []
    hierarchy_nodes: list[HierarchyNode] = []
    for batch in jsm_connector.poll_source(0, time.time()):
        for item in batch:
            if isinstance(item, Document):
                docs.append(item)
            elif isinstance(item, HierarchyNode):
                hierarchy_nodes.append(item)

    assert len(docs) > 0
    for doc in docs:
        assert doc.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
        assert doc.metadata.get("issue_key")
