import time

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)
from onyx.connectors.models import SlimDocument
from tests.daily.connectors.utils import load_all_from_connector
from tests.utils.secret_names import TestSecret

pytestmark = pytest.mark.secrets(
    TestSecret.JIRA_BASE_URL,
    TestSecret.JIRA_USER_EMAIL,
    TestSecret.JIRA_API_TOKEN,
    TestSecret.JSM_PROJECT_KEY,
)


def test_service_project_tickets(test_secrets: dict[TestSecret, str]) -> None:
    """Use a service project with at least two tickets and no attachments."""
    project_key = test_secrets[TestSecret.JSM_PROJECT_KEY]
    connector = JiraServiceManagementConnector(
        jira_base_url=test_secrets[TestSecret.JIRA_BASE_URL],
        project_key=project_key,
    )
    connector.load_credentials(
        {
            "jira_user_email": test_secrets[TestSecret.JIRA_USER_EMAIL],
            "jira_api_token": test_secrets[TestSecret.JIRA_API_TOKEN],
        }
    )
    connector.validate_connector_settings()
    output = load_all_from_connector(connector, start=0, end=time.time())
    assert not output.failures
    assert len(output.documents) >= 2
    ids = {doc.id for doc in output.documents}
    assert len(ids) == len(output.documents)
    for doc in output.documents:
        assert doc.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
        assert doc.metadata["project"] == project_key
        assert doc.sections
        assert doc.doc_updated_at is not None
    slim_ids = {
        doc.id
        for batch in connector.retrieve_all_slim_docs()
        for doc in batch
        if isinstance(doc, SlimDocument)
    }
    assert slim_ids == ids
