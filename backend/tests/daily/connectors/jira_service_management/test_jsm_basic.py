"""
Daily integration tests for the Jira Service Management connector.

These tests require real JSM credentials set in environment variables.
They are skipped automatically in CI environments where credentials are absent.

To run locally:
    export JSM_BASE_URL="https://your-domain.atlassian.net"
    export JSM_PROJECT_KEY="SERVICEDESK"   # optional — tests all projects if unset
    export JSM_USER_EMAIL="you@example.com"
    export JSM_API_TOKEN="your-api-token"
    pytest backend/tests/daily/connectors/jira_service_management/
"""

import os

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)
from tests.daily.connectors.utils import load_all_from_connector


# ---------------------------------------------------------------------------
# Environment variables — read once at module level
# ---------------------------------------------------------------------------

JSM_BASE_URL = os.environ.get("JSM_BASE_URL", "")
JSM_PROJECT_KEY = os.environ.get("JSM_PROJECT_KEY", "")
JSM_USER_EMAIL = os.environ.get("JSM_USER_EMAIL", "")
JSM_API_TOKEN = os.environ.get("JSM_API_TOKEN", "")

pytestmark = pytest.mark.skipif(
    not all([JSM_BASE_URL, JSM_USER_EMAIL, JSM_API_TOKEN]),
    reason="JSM_BASE_URL, JSM_USER_EMAIL, and JSM_API_TOKEN must be set to run daily tests",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def jsm_connector() -> JiraServiceManagementConnector:
    """Return a JSM connector loaded with credentials from environment variables."""
    connector = JiraServiceManagementConnector(
        jira_base_url=JSM_BASE_URL,
        project_key=JSM_PROJECT_KEY or None,
        comment_email_blacklist=[],
    )
    connector.load_credentials(
        {
            "jira_user_email": JSM_USER_EMAIL,
            "jira_api_token": JSM_API_TOKEN,
        }
    )
    return connector


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_validate_connector_settings(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    """Connector must pass validation with valid credentials."""
    jsm_connector.validate_connector_settings()


def test_documents_returned(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    """At least one document must be indexed from the JSM project."""
    result = load_all_from_connector(
        connector=jsm_connector,
        start=0,
        end=9_999_999_999,
    )
    assert len(result.documents) > 0, (
        "Expected at least one JSM document. "
        "Check that JSM_PROJECT_KEY points to a project with at least one ticket."
    )


def test_documents_have_jsm_source(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    """Every indexed document must carry DocumentSource.JIRA_SERVICE_MANAGEMENT."""
    result = load_all_from_connector(
        connector=jsm_connector,
        start=0,
        end=9_999_999_999,
    )
    for doc in result.documents:
        assert doc.source == DocumentSource.JIRA_SERVICE_MANAGEMENT, (
            f"Document {doc.id!r} has wrong source: {doc.source!r}. "
            f"Expected {DocumentSource.JIRA_SERVICE_MANAGEMENT!r}."
        )


def test_slim_docs_perm_sync(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    """retrieve_all_slim_docs_perm_sync must yield at least one non-empty batch."""
    batches = list(jsm_connector.retrieve_all_slim_docs_perm_sync(start=0))
    assert len(batches) > 0, (
        "Expected at least one batch from retrieve_all_slim_docs_perm_sync"
    )
    total_docs = sum(len(batch) for batch in batches)
    assert total_docs > 0, "Batches were returned but all were empty"


def test_sla_metadata_logged(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    """
    Log which SLA and JSM metadata keys were discovered on this instance.

    This test always passes — SLA fields are optional and depend on the
    Jira instance configuration. Its purpose is visibility: running with -s
    shows which SLA fields were found, helping diagnose misconfigured connectors.
    """
    result = load_all_from_connector(
        connector=jsm_connector,
        start=0,
        end=9_999_999_999,
    )
    jsm_keys: set[str] = set()
    for doc in result.documents:
        for key in doc.metadata:
            if key.startswith("sla_") or key.startswith("jsm_"):
                jsm_keys.add(key)

    if jsm_keys:
        print(f"\nJSM/SLA metadata keys found on this instance: {sorted(jsm_keys)}")
    else:
        print(
            "\nNo SLA/JSM metadata found. "
            "The Jira instance may not have SLA fields configured, "
            "or the API token may lack read access to field metadata."
        )
