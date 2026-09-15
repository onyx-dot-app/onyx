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
    TestSecret.JIRA_API_TOKEN_SCOPED,
)


def _make_connector(
    test_secrets: dict[TestSecret, str],
    project_key: str = "ITSM",
    scoped_token: bool = False,
) -> JiraServiceManagementConnector:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://danswerai.atlassian.net",
        project_key=project_key,
        comment_email_blacklist=[],
        scoped_token=scoped_token,
    )
    connector.load_credentials(
        {
            "jira_user_email": test_secrets[TestSecret.JIRA_USER_EMAIL],
            "jira_api_token": (
                test_secrets[TestSecret.JIRA_API_TOKEN_SCOPED]
                if scoped_token
                else test_secrets[TestSecret.JIRA_API_TOKEN]
            ),
        }
    )
    return connector


@pytest.fixture
def jsm_connector(
    test_secrets: dict[TestSecret, str],
) -> JiraServiceManagementConnector:
    return _make_connector(test_secrets)


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_jsm_connector_basic(
    reset: None,  # noqa: ARG001
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    _test_jsm_connector_basic(jsm_connector)


def _test_jsm_connector_basic(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    docs = load_all_from_connector(
        connector=jsm_connector,
        start=0,
        end=time.time(),
    ).documents

    assert len(docs) > 0, "No documents were retrieved from the Jira Service Management connector"

    for doc in docs:
        assert isinstance(doc, Document)
        assert doc.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
        assert doc.metadata.get("project") == jsm_connector.jira_project
        assert doc.id.startswith(jsm_connector.jira_base)
