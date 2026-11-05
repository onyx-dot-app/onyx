"""Daily integration test for the Jira Service Management connector (#2281)."""

import os
import time
import pytest

from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)


@pytest.mark.skipif(
    not os.environ.get("JSM_BASE_URL"),
    reason="JSM daily integration environment variables not set",
)
def test_jira_service_management_connector_daily() -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url=os.environ["JSM_BASE_URL"],
        project_key=os.environ.get("JSM_PROJECT_KEY", "ITSD"),
    )
    connector.load_credentials(
        {
            "jira_user_email": os.environ.get("JSM_USER_EMAIL", ""),
            "jira_api_token": os.environ.get("JSM_USER_KEY", ""),
        }
    )
    assert connector.validate_credentials() is True
    batches = list(connector.load_from_state())
    assert isinstance(batches, list)
    now = time.time()
    polled = list(connector.poll_source(now - 86400, now))
    assert isinstance(polled, list)
