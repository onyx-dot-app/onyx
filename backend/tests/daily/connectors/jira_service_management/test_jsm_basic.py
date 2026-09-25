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

# Credentials are the same as the Jira connector's; the base URL must point at
# a Jira instance with a Jira Service Management project whose key is
# JSM_PROJECT_KEY. For reference, danswerai.atlassian.net uses the "ITSM"
# service desk project.
JSM_BASE_URL = "https://danswerai.atlassian.net"
JSM_PROJECT_KEY = "ITSM"

pytestmark = pytest.mark.secrets(
    TestSecret.JIRA_USER_EMAIL,
    TestSecret.JIRA_API_TOKEN,
)


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


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_jsm_connector_basic(
    reset: None,  # noqa: ARG001
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    docs = load_all_from_connector(
        connector=jsm_connector,
        start=0,
        end=time.time(),
    ).documents

    assert len(docs) > 0, (
        "No documents were retrieved from the Jira Service Management connector"
    )

    for doc in docs:
        assert isinstance(doc, Document)
        # Every ticket is branded as a Jira Service Management document
        assert doc.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
        # Document IDs are the browse URLs of the tickets
        assert doc.id.startswith(JSM_BASE_URL)
        # Tickets are scoped to the configured service desk project
        assert doc.metadata.get("project") == JSM_PROJECT_KEY
        # JSM enrichment: every JSM ticket carries its request type
        assert doc.metadata.get("customer_request_type")

        assert len(doc.sections) == 1
        assert doc.sections[0].link == doc.id


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_jsm_connector_slim_docs(
    reset: None,  # noqa: ARG001
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    from onyx.connectors.models import SlimDocument

    slim_batches = list(jsm_connector.retrieve_all_slim_docs(start=0, end=time.time()))
    slim_docs = [
        slim_doc
        for batch in slim_batches
        for slim_doc in batch
        if isinstance(slim_doc, SlimDocument)
    ]

    assert len(slim_docs) > 0, "No slim documents were retrieved"
    for slim_doc in slim_docs:
        assert slim_doc.id.startswith(JSM_BASE_URL)
