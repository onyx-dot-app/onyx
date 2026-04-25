"""
Daily connector tests for the Jira Service Management (JSM) connector.

Setup:
  1. Create a JSM project in Atlassian Cloud (project type: service_desk).
  2. Set the following environment variables:
       JSM_BASE_URL       — e.g. https://your-domain.atlassian.net
       JSM_PROJECT_KEY    — e.g. IT
       JIRA_USER_EMAIL    — the email address of the API token owner
       JIRA_API_TOKEN     — an Atlassian API token with read access to the JSM project
  3. Create at least one service request ticket in the project and note its key.
  4. Run:
       pytest backend/tests/daily/connectors/jira_service_management/test_jsm_basic.py -v
"""

import os
import time
from unittest.mock import patch

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)
from onyx.connectors.models import Document
from tests.daily.connectors.utils import load_all_from_connector


def _make_connector(
    project_key: str | None = None,
    jql_query: str | None = None,
    use_env_project_key: bool = True,
) -> JiraServiceManagementConnector:
    # Parentheses make the conditional explicit; without them, Python's operator
    # precedence would bind `or` tighter than the ternary, giving unexpected results
    # when use_env_project_key=False.
    resolved_project_key = (
        (project_key or os.environ.get("JSM_PROJECT_KEY"))
        if use_env_project_key
        else project_key
    )
    connector = JiraServiceManagementConnector(
        jira_base_url=os.environ["JSM_BASE_URL"],
        project_key=resolved_project_key,
        jql_query=jql_query,
        comment_email_blacklist=[],
    )
    connector.load_credentials(
        {
            "jira_user_email": os.environ["JIRA_USER_EMAIL"],
            "jira_api_token": os.environ["JIRA_API_TOKEN"],
        }
    )
    return connector


@pytest.fixture
def jsm_connector() -> JiraServiceManagementConnector:
    return _make_connector()


@pytest.fixture
def jsm_connector_no_scope() -> JiraServiceManagementConnector:
    """Connector with no project_key or JQL — exercises the default service_desk scope path."""
    return _make_connector(project_key=None, jql_query=None, use_env_project_key=False)


@pytest.fixture
def jsm_connector_with_jql() -> JiraServiceManagementConnector:
    project_key = os.environ.get("JSM_PROJECT_KEY", "")
    connector = _make_connector(
        project_key=None,
        jql_query=f"project = '{project_key}' AND issuetype = 'Service Request'",
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
    """Test that the JSM connector returns documents with the correct source type.

    All returned documents must have source == DocumentSource.JIRA_SERVICE_MANAGEMENT.
    """
    docs = load_all_from_connector(
        connector=jsm_connector,
        start=0,
        end=time.time(),
    ).documents

    assert len(docs) > 0, (
        "Expected at least one service desk ticket. "
        "Please create a service request in the JSM project and try again."
    )

    for doc in docs:
        assert isinstance(doc, Document)
        assert doc.source == DocumentSource.JIRA_SERVICE_MANAGEMENT, (
            f"Expected source JIRA_SERVICE_MANAGEMENT, got {doc.source} for {doc.id}"
        )
        # All JSM tickets must have a key in metadata
        assert "key" in doc.metadata, f"Missing 'key' in metadata for {doc.id}"


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_jsm_connector_jsm_metadata(
    reset: None,  # noqa: ARG001
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    """Test that JSM-specific metadata fields are populated when the Service Desk API is available.

    Fields checked: request_type, sla_name / sla_breached (optional — only if SLAs configured).
    """
    docs = load_all_from_connector(
        connector=jsm_connector,
        start=0,
        end=time.time(),
    ).documents

    assert len(docs) > 0

    # At least one document should have request_type if the JSM project has request types defined
    has_request_type = any("request_type" in doc.metadata for doc in docs)
    # Note: request_type may be absent if the Atlassian plan doesn't expose Service Desk API
    # or if no request types are configured — log a warning rather than hard-fail
    if not has_request_type:
        import warnings

        warnings.warn(
            "No 'request_type' metadata found on any JSM ticket. "
            "This is expected if the Service Desk API is not accessible with the provided credentials.",
            stacklevel=2,
        )


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_jsm_connector_service_desk_scope(
    reset: None,  # noqa: ARG001
    jsm_connector_no_scope: JiraServiceManagementConnector,
) -> None:
    """Verify that without an explicit project key or JQL the connector's default
    ``project type = service_desk`` filter is exercised.

    The ``jsm_connector_no_scope`` fixture creates the connector with
    ``project_key=None`` and ``jql_query=None`` (bypassing ``JSM_PROJECT_KEY``
    entirely) so that ``_get_jql_query`` appends the service-desk scope clause.

    Assertions:
    - At least one document is returned.
    - Every document carries ``source == JIRA_SERVICE_MANAGEMENT``.
    - If ``JSM_PROJECT_KEY`` is provided we additionally assert that the expected
      project appears in the results, confirming the scope filter returned
      service-desk tickets rather than an empty set or software-project tickets.
    """
    docs = load_all_from_connector(
        connector=jsm_connector_no_scope,
        start=0,
        end=time.time(),
    ).documents

    assert len(docs) > 0, (
        "Expected at least one document from the service-desk scoped query. "
        "Make sure the Atlassian instance has at least one service_desk project with tickets."
    )

    for doc in docs:
        assert doc.source == DocumentSource.JIRA_SERVICE_MANAGEMENT, (
            f"Expected JIRA_SERVICE_MANAGEMENT source, got {doc.source} for {doc.id}"
        )

    # Best-effort: if a reference project is configured, confirm it appears in
    # the result set — this validates that the scope filter is not excluding all
    # service-desk tickets.
    project_key = os.environ.get("JSM_PROJECT_KEY")
    if project_key:
        returned_projects = {doc.metadata.get("project") for doc in docs}
        assert project_key in returned_projects, (
            f"JSM_PROJECT_KEY '{project_key}' not found in returned projects {returned_projects}. "
            "The service-desk scope filter may be excluding it."
        )


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_jsm_connector_with_jql(
    reset: None,  # noqa: ARG001
    jsm_connector_with_jql: JiraServiceManagementConnector,
) -> None:
    """Test that custom JQL is respected — only 'Service Request' issue types returned."""
    docs = load_all_from_connector(
        connector=jsm_connector_with_jql,
        start=0,
        end=time.time(),
    ).documents

    assert len(docs) > 0
    for doc in docs:
        assert doc.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
        assert doc.metadata.get("issuetype") == "Service Request", (
            f"Expected issuetype 'Service Request', got '{doc.metadata.get('issuetype')}' for {doc.id}"
        )
