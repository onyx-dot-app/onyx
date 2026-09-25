import time

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


def _build_connector(
    test_secrets: dict[TestSecret, str],
) -> JiraServiceManagementConnector:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://danswerai.atlassian.net",
        project_key="SUP",
        comment_email_blacklist=[],
    )
    connector.load_credentials(
        {
            "jira_user_email": test_secrets[TestSecret.JIRA_USER_EMAIL],
            "jira_api_token": test_secrets[TestSecret.JIRA_API_TOKEN],
        }
    )
    return connector


def test_jsm_connector_indexes_service_desk_tickets(
    reset: None,  # noqa: ARG001
    test_secrets: dict[TestSecret, str],
) -> None:
    connector = _build_connector(test_secrets)
    connector.validate_connector_settings()

    documents = load_all_from_connector(
        connector=connector,
        start=0,
        end=time.time(),
    ).documents

    assert documents
    for document in documents:
        assert isinstance(document, Document)
        assert document.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
        assert document.id.startswith("https://danswerai.atlassian.net/browse/SUP-")
        assert document.metadata["project"] == "SUP"
