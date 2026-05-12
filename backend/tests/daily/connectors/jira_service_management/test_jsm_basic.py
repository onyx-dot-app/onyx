"""Daily connector tests for the Jira Service Management connector.

To run these tests you need to set the following environment variables:
  JIRA_BASE_URL      - e.g. https://yourorg.atlassian.net
  JSM_PROJECT_KEY    - key of a JSM service-desk project (e.g. IT)
  JIRA_USER_EMAIL    - email of the Jira user
  JIRA_API_TOKEN     - API token for the Jira user

The project should contain at least one Service Request issue so that
the request-type metadata extraction can be verified.
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


def _make_connector() -> JiraServiceManagementConnector:
    connector = JiraServiceManagementConnector(
        jira_base_url=os.environ["JIRA_BASE_URL"],
        project_key=os.environ.get("JSM_PROJECT_KEY"),
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


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_jsm_connector_basic(
    reset: None,  # noqa: ARG001
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    """Verify the JSM connector returns documents with the correct source and metadata."""
    result = load_all_from_connector(
        connector=jsm_connector,
        start=0,
        end=time.time(),
    )

    docs: list[Document] = result.documents
    assert len(docs) > 0, "Expected at least one document from the JSM project"

    for doc in docs:
        # Source must be JIRA_SERVICE_MANAGEMENT, not JIRA
        assert doc.source == DocumentSource.JIRA_SERVICE_MANAGEMENT, (
            f"Document {doc.id} has unexpected source: {doc.source}"
        )

        # Standard Jira fields must be present
        assert "key" in doc.metadata, f"Document {doc.id} is missing 'key' metadata"
        assert "status" in doc.metadata, (
            f"Document {doc.id} is missing 'status' metadata"
        )
        assert "project" in doc.metadata, (
            f"Document {doc.id} is missing 'project' metadata"
        )

        # Document must have at least one section with a link
        assert len(doc.sections) > 0
        assert doc.sections[0].link is not None


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_jsm_connector_jsm_metadata(
    reset: None,  # noqa: ARG001
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    """Verify that at least one document has JSM-specific metadata fields."""
    result = load_all_from_connector(
        connector=jsm_connector,
        start=0,
        end=time.time(),
    )
    docs: list[Document] = result.documents
    assert len(docs) > 0

    # At least one document should have a request_type field if the project
    # has Service Request issues with a request type configured.
    jsm_fields = {"request_type", "sla_time_to_first_response", "sla_time_to_resolution"}
    docs_with_jsm_fields = [
        doc for doc in docs if jsm_fields & set(doc.metadata.keys())
    ]

    # We don't assert a count here because SLA / request-type fields are only
    # present when the JSM project has them configured.  We simply log to help
    # with manual verification.
    if not docs_with_jsm_fields:
        pytest.skip(
            "No JSM-specific metadata fields found; the project may not have "
            "request types or SLAs configured."
        )

    for doc in docs_with_jsm_fields:
        # request_type must be a non-empty string when present
        if "request_type" in doc.metadata:
            assert isinstance(doc.metadata["request_type"], str)
            assert len(doc.metadata["request_type"]) > 0

        # SLA breached flags must be "true" or "false" when present
        for breached_key in (
            "sla_time_to_first_response_breached",
            "sla_time_to_resolution_breached",
        ):
            if breached_key in doc.metadata:
                assert doc.metadata[breached_key] in ("true", "false"), (
                    f"Unexpected value for {breached_key}: {doc.metadata[breached_key]}"
                )


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_jsm_connector_slim_docs(
    reset: None,  # noqa: ARG001
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    """Verify the slim docs path returns IDs matching those from the full fetch."""
    full_result = load_all_from_connector(
        connector=jsm_connector,
        start=0,
        end=time.time(),
    )

    slim_doc_ids: set[str] = set()
    for batch in jsm_connector.retrieve_all_slim_docs_perm_sync():
        for item in batch:
            # HierarchyNodes don't have an 'id' attribute the same way
            if hasattr(item, "id"):
                slim_doc_ids.add(item.id)

    full_doc_ids = {doc.id for doc in full_result.documents}

    # Every full document should also appear in the slim docs
    missing = full_doc_ids - slim_doc_ids
    assert not missing, (
        f"The following document IDs are present in full fetch but missing from slim: {missing}"
    )
