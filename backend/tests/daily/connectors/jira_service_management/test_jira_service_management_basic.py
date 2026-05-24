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

pytestmark = [
    pytest.mark.skipif(
        not os.getenv("JIRA_SERVICE_MANAGEMENT_PROJECT_KEY"),
        reason="Set JIRA_SERVICE_MANAGEMENT_PROJECT_KEY to run this test",
    ),
    pytest.mark.secrets(
        TestSecret.JIRA_USER_EMAIL,
        TestSecret.JIRA_API_TOKEN,
    ),
]


def _jsm_project_key() -> str:
    project_key = os.getenv("JIRA_SERVICE_MANAGEMENT_PROJECT_KEY")
    assert project_key is not None
    return project_key


def _make_connector(
    test_secrets: dict[TestSecret, str],
) -> JiraServiceManagementConnector:
    connector = JiraServiceManagementConnector(
        jira_base_url=os.getenv("JIRA_SERVICE_MANAGEMENT_BASE_URL")
        or test_secrets.get(TestSecret.JIRA_BASE_URL)
        or "https://danswerai.atlassian.net",
        project_key=_jsm_project_key(),
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
    reset: None,  # noqa: ARG001
    mock_get_api_key: object,  # noqa: ARG001
    test_secrets: dict[TestSecret, str],
) -> None:
    connector = _make_connector(test_secrets)

    connector.validate_connector_settings()
    docs = load_all_from_connector(
        connector=connector,
        start=0,
        end=time.time(),
    ).documents

    assert docs
    assert all(doc.source == DocumentSource.JIRA_SERVICE_MANAGEMENT for doc in docs)
    assert all(doc.metadata.get("project") == connector.jira_project for doc in docs)
