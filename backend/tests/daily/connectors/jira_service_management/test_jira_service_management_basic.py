import os
import time

from onyx.configs.constants import DocumentSource
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)
from onyx.connectors.models import Document


def test_jira_service_management_connector_basic() -> None:
    base_url = os.environ["JSM_BASE_URL"]
    user_email = os.environ["JSM_USER_EMAIL"]
    api_token = os.environ["JSM_API_TOKEN"]

    connector = JiraServiceManagementConnector()
    connector.load_credentials(
        {
            "jsm_base_url": base_url,
            "jsm_user_email": user_email,
            "jsm_api_token": api_token,
        }
    )
    connector.validate_connector_settings()

    now = time.time()
    batches = list(connector.poll_source(0, now))
    docs = [doc for batch in batches for doc in batch]
    assert docs, "Expected at least one Jira Service Management document"
    for doc in docs:
        assert isinstance(doc, Document)
        assert doc.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
