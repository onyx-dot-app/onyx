import os
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
    TestSecret.JIRA_BASE_URL,
    TestSecret.JIRA_USER_EMAIL,
    TestSecret.JIRA_API_TOKEN,
)


@pytest.fixture
def jsm_connector(
    test_secrets: dict[TestSecret, str],
) -> JiraServiceManagementConnector:
    base_url = test_secrets[TestSecret.JIRA_BASE_URL]
    project_key = os.environ.get("JSM_PROJECT_KEY")
    connector = JiraServiceManagementConnector(
        jira_base_url=base_url,
        project_key=project_key,
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
def test_jira_service_management_connector_basic(
    _mock_unstructured: object,
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    docs = load_all_from_connector(
        connector=jsm_connector,
        start=0,
        end=time.time(),
    ).documents

    assert len(docs) > 0
    seen_ids: set[str] = set()
    for doc in docs:
        assert doc.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
        assert doc.id.startswith(f"{jsm_connector.jira_base}/browse/")
        assert doc.id not in seen_ids
        seen_ids.add(doc.id)
        assert len(doc.sections) >= 1
        if jsm_connector.jira_project:
            assert doc.metadata.get("project") == jsm_connector.jira_project
