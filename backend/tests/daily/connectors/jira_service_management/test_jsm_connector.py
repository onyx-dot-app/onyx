"""Basic integration tests for the Jira Service Management connector.

Setup
-----
Export the following environment variables before running:

    export JSM_BASE_URL="https://your-org.atlassian.net"
    export JSM_USER_EMAIL="you@example.com"
    export JSM_API_TOKEN="your-api-token"
    export JSM_PROJECT_KEY="SD"   # optional — omit to test all service desks

Then run::

    pytest backend/tests/daily/connectors/jira_service_management/ -v
"""
import os
import time

import pytest

from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)


@pytest.fixture()
def connector() -> JiraServiceManagementConnector:
    base_url = os.environ.get("JSM_BASE_URL")
    user_email = os.environ.get("JSM_USER_EMAIL")
    api_token = os.environ.get("JSM_API_TOKEN")

    if not base_url or not user_email or not api_token:
        pytest.fail(
            "JSM credentials not configured — set JSM_BASE_URL, JSM_USER_EMAIL, "
            "and JSM_API_TOKEN env vars. Tests cannot run without credentials."
        )

    conn = JiraServiceManagementConnector(
        jsm_base_url=base_url,
        project_key=os.environ.get("JSM_PROJECT_KEY"),
    )
    conn.load_credentials(
        {
            "jsm_user_email": user_email,
            "jsm_api_token": api_token,
        }
    )
    return conn


def test_load_from_state_returns_documents(connector: JiraServiceManagementConnector) -> None:
    """Verify that load_from_state yields at least one document."""
    docs = []
    for batch in connector.load_from_state():
        docs.extend(batch)
        if len(docs) >= 5:
            break

    assert len(docs) > 0, "Expected at least one document from load_from_state."
    doc = docs[0]
    assert doc.id.startswith("JSM_"), f"Unexpected id prefix: {doc.id}"
    assert doc.source.value == "jira_service_management"
    assert doc.semantic_identifier, "Document should have a non-empty semantic_identifier."


def test_poll_source_returns_documents(connector: JiraServiceManagementConnector) -> None:
    """Verify that poll_source yields documents within the last 30 days."""
    now = time.time()
    thirty_days_ago = now - 30 * 86400

    docs = []
    for batch in connector.poll_source(thirty_days_ago, now):
        docs.extend(batch)
        if len(docs) >= 5:
            break

    # May be empty if no issues updated in the last 30 days — that is acceptable
    for doc in docs:
        assert doc.doc_updated_at is not None, "poll_source docs should have updated_at."
        assert thirty_days_ago <= doc.doc_updated_at <= now, (
            f"poll_source doc updated_at {doc.doc_updated_at} falls outside "
            f"the requested window [{thirty_days_ago}, {now}] — poll filtering regressed."
        )


def test_validate_connector_settings(connector: JiraServiceManagementConnector) -> None:
    """Verify that validate_connector_settings does not raise."""
    connector.validate_connector_settings()


def test_document_has_expected_fields(connector: JiraServiceManagementConnector) -> None:
    """Spot-check document field completeness."""
    docs = []
    for batch in connector.load_from_state():
        docs.extend(batch)
        if docs:
            break

    if not docs:
        pytest.skip("No documents returned — skipping field check.")

    doc = docs[0]
    assert doc.sections, "Document should have at least one section."
    section = doc.sections[0]
    assert section.link, "Section should have a link."
    assert section.text, "Section should have text content."
    assert doc.metadata.get("project"), "Document should include 'project' metadata."
    assert doc.metadata.get("status"), "Document should include 'status' metadata."

