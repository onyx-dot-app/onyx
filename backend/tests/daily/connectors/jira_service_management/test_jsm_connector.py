import os
import time
from unittest.mock import patch

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)
from tests.daily.connectors.utils import load_all_from_connector


@pytest.fixture
def jsm_connector() -> JiraServiceManagementConnector:
    connector = JiraServiceManagementConnector(
        jira_base_url=os.environ["JSM_BASE_URL"],
        project_key=os.environ.get("JSM_PROJECT_KEY"),
        comment_email_blacklist=[],
    )
    connector.load_credentials(
        {
            "jira_user_email": os.environ["JSM_USER_EMAIL"],
            "jira_api_token": os.environ["JSM_API_TOKEN"],
        }
    )
    return connector


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_jsm_connector_basic(
    reset: None,  # noqa: ARG001
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    """Test that the JSM connector can fetch service requests and
    produce documents with source=JIRA_SERVICE_MANAGEMENT."""
    docs = load_all_from_connector(
        connector=jsm_connector,
        start=0,
        end=time.time(),
    ).documents
    assert len(docs) > 0

    for doc in docs:
        assert doc.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
        assert doc.id is not None
        assert doc.semantic_identifier is not None
        assert len(doc.sections) > 0
        # Verify standard Jira metadata is present
        assert "key" in doc.metadata
        assert "status" in doc.metadata
        # Verify JSM-specific metadata when available
        if "request_type" in doc.metadata:
            assert isinstance(doc.metadata["request_type"], str)
            assert len(doc.metadata["request_type"]) > 0


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_jsm_connector_validate_settings(
    reset: None,  # noqa: ARG001
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    """Test that connector validation succeeds with valid credentials."""
    jsm_connector.validate_connector_settings()
