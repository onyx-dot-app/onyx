"""Daily test for the Jira Service Management connector (DRAFT).

Follows the connectors README: daily tests live under
``backend/tests/daily/connectors/<source>/`` and run against a live source.
This one needs a Jira Cloud site with a JSM project that holds at least one
request with a public comment.

Required environment (via .vscode/.env or AWS Secrets Manager, see
backend/tests/utils/aws_secrets.py):
    JSM_TEST_BASE_URL     e.g. https://example.atlassian.net
    JSM_TEST_PROJECT_KEY  e.g. SUPPORT
    JSM_TEST_USER_EMAIL   Atlassian account email of the API token owner
    JSM_TEST_API_TOKEN    Atlassian API token

TODO before submission: align the secret names with TestSecret entries and
the fixtures used by test_jira_basic.py, and pin the expected request key of
the seeded ticket instead of accepting any document.
"""

import os
import time

import pytest

from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)


@pytest.fixture(scope="module")
def connector() -> JiraServiceManagementConnector:
    conn = JiraServiceManagementConnector(
        jira_base_url=os.environ["JSM_TEST_BASE_URL"],
        project_key=os.environ["JSM_TEST_PROJECT_KEY"],
    )
    conn.load_credentials(
        {
            "jira_user_email": os.environ["JSM_TEST_USER_EMAIL"],
            "jira_api_token": os.environ["JSM_TEST_API_TOKEN"],
        }
    )
    return conn


def test_validate_settings(connector: JiraServiceManagementConnector) -> None:
    connector.validate_connector_settings()


def test_load_from_state_returns_seeded_request(
    connector: JiraServiceManagementConnector,
) -> None:
    docs = list(connector.load_from_state())
    assert len(docs) >= 1
    doc = docs[0]
    assert doc.semantic_identifier.startswith(os.environ["JSM_TEST_PROJECT_KEY"])
    assert doc.metadata.get("request_type")
    assert doc.metadata.get("status")


def test_poll_source_recent_window(
    connector: JiraServiceManagementConnector,
) -> None:
    now = time.time()
    docs = list(connector.poll_source(now - 7 * 24 * 3600, now + 24 * 3600))
    assert len(docs) >= 1


def test_slim_docs_match_full_docs(
    connector: JiraServiceManagementConnector,
) -> None:
    full_ids = {doc.id for doc in connector.load_from_state()}
    slim_ids = {
        slim.id
        for batch in connector.retrieve_all_slim_docs()
        for slim in batch
    }
    assert slim_ids == full_ids
