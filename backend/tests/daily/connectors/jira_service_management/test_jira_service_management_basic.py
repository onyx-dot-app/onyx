import os
import time

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)
from onyx.connectors.models import Document


def test_jira_service_management_connector_basic() -> None:
    base_url = os.environ.get("JSM_BASE_URL")
    user_email = os.environ.get("JSM_USER_EMAIL")
    api_token = os.environ.get("JSM_API_TOKEN")

    if not base_url or not user_email or not api_token:
        pytest.skip("Requires live Jira Service Management credentials in environment")

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
    for batch in batches:
        for doc in batch:
            if isinstance(doc, Document):
                assert doc.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
                assert doc.id.startswith("JSM_REQUEST_")
