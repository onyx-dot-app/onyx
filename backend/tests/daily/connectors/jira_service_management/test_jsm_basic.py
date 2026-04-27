import os
import time
from unittest.mock import patch

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)
from onyx.connectors.models import Document
from tests.daily.connectors.utils import load_all_from_connector


def _make_connector() -> JiraServiceManagementConnector:
    connector = JiraServiceManagementConnector(
        jira_base_url=os.environ["JSM_JIRA_BASE_URL"],
        jsm_project_key=os.environ["JSM_PROJECT_KEY"],
        comment_email_blacklist=[],
    )
    connector.load_credentials(
        {
            "jira_user_email": os.environ["JSM_USER_EMAIL"],
            "jira_api_token": os.environ["JSM_API_TOKEN"],
        }
    )
    return connector


@pytest.fixture
def jsm_connector() -> JiraServiceManagementConnector:
    return _make_connector()


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_jsm_connector_basic(
    reset: None,  # noqa: ARG001
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    output = load_all_from_connector(
        connector=jsm_connector,
        start=0,
        end=time.time(),
    )
    docs = output.documents

    assert len(docs) > 0, "Expected at least one document from JSM project"

    for doc in docs:
        assert isinstance(doc, Document)
        assert doc.source == DocumentSource.JIRA_SERVICE_MANAGEMENT, (
            f"Expected source JIRA_SERVICE_MANAGEMENT, got {doc.source!r} for {doc.id}"
        )
        # All JSM tickets must have standard Jira metadata fields
        assert "key" in doc.metadata, f"Missing 'key' in metadata for {doc.id}"
        assert "status" in doc.metadata, f"Missing 'status' in metadata for {doc.id}"
        assert "issuetype" in doc.metadata, (
            f"Missing 'issuetype' in metadata for {doc.id}"
        )


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_jsm_connector_customer_portal_url(
    reset: None,  # noqa: ARG001
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    """When service desk ID is resolved, documents should carry customer_portal_url."""
    if jsm_connector._service_desk_id is None:
        pytest.skip("Service desk ID could not be resolved; skipping portal URL test")

    output = load_all_from_connector(
        connector=jsm_connector,
        start=0,
        end=time.time(),
    )
    docs_with_portal_url = [
        doc for doc in output.documents if "customer_portal_url" in doc.metadata
    ]
    assert len(docs_with_portal_url) > 0, (
        "Expected at least one document to have customer_portal_url in metadata"
    )
    for doc in docs_with_portal_url:
        url: str = doc.metadata["customer_portal_url"]
        assert url.startswith("http"), f"customer_portal_url looks malformed: {url!r}"
        assert "/servicedesk/customer/portal/" in url


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_jsm_validate_connector_settings(
    reset: None,  # noqa: ARG001
) -> None:
    jsm_connector = _make_connector()
    jsm_connector.validate_connector_settings()  # should not raise


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_jsm_validate_rejects_non_jsm_project(
    reset: None,  # noqa: ARG001
) -> None:
    """validate_connector_settings should raise ConnectorValidationError for a
    non-Service-Desk project key."""
    non_jsm_key = os.environ.get("JSM_NON_SERVICE_DESK_PROJECT_KEY", "")
    if not non_jsm_key:
        pytest.skip(
            "JSM_NON_SERVICE_DESK_PROJECT_KEY not set; skipping negative validation test"
        )

    connector = JiraServiceManagementConnector(
        jira_base_url=os.environ["JSM_JIRA_BASE_URL"],
        jsm_project_key=non_jsm_key,
    )
    connector.load_credentials(
        {
            "jira_user_email": os.environ["JSM_USER_EMAIL"],
            "jira_api_token": os.environ["JSM_API_TOKEN"],
        }
    )
    with pytest.raises(ConnectorValidationError, match="not a Jira Service Management"):
        connector.validate_connector_settings()
