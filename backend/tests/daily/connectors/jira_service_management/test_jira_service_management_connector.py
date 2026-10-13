import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)
from onyx.connectors.models import HierarchyNode
from tests.utils.secret_names import TestSecret

pytestmark = pytest.mark.secrets(
    TestSecret.JSM_PROJECT_NAME,
    TestSecret.JSM_BASE_URL,
    TestSecret.JSM_USER_EMAIL,
    TestSecret.JSM_API_TOKEN,
)


@pytest.fixture
def jsm_connector(
    test_secrets: dict[TestSecret, str],
) -> JiraServiceManagementConnector:
    connector = JiraServiceManagementConnector(
        project_name=test_secrets[TestSecret.JSM_PROJECT_NAME],
        jira_base_url=test_secrets[TestSecret.JSM_BASE_URL],
    )
    connector.load_credentials(
        {
            "jira_user_email": test_secrets[TestSecret.JSM_USER_EMAIL],
            "jira_api_token": test_secrets[TestSecret.JSM_API_TOKEN],
        }
    )
    return connector


def test_jsm_connector_basic(jsm_connector: JiraServiceManagementConnector) -> None:
    doc_batch_generator = jsm_connector.load_from_state()

    doc_batch = next(doc_batch_generator)
    assert len(doc_batch) > 0

    main_doc = doc_batch[0]
    assert not isinstance(main_doc, HierarchyNode)

    # Basic document properties
    assert main_doc.id.startswith("jsm-")
    assert main_doc.source == DocumentSource.JIRA_SERVICE_MANAGEMENT

    # Metadata checks
    assert "status" in main_doc.metadata
    assert "issue_type" in main_doc.metadata
    assert "jira_issue_key" in main_doc.metadata

    # Section checks
    assert len(main_doc.sections) == 1
    section = main_doc.sections[0]

    # The section links back to the request in the Jira UI
    assert "/browse/" in section.link
    assert section.text

    assert main_doc.semantic_identifier


def test_jsm_connector_poll_source_no_changes(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    # A window far in the future should return no documents.
    future_start = 4102444800  # 2100-01-01
    future_end = 4102531200
    doc_batches = list(
        jsm_connector.poll_source(start=future_start, end=future_end)
    )
    all_docs = [doc for batch in doc_batches for doc in batch]
    assert len(all_docs) == 0
