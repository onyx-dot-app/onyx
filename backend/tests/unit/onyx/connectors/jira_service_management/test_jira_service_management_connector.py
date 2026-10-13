import time
from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock

from onyx.configs.constants import DocumentSource
from onyx.connectors.factory import identify_connector_class
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.jira.connector import JiraConnector
from onyx.connectors.jira_service_management.config import (
    JiraServiceManagementConnectorConfig,
)
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)
from onyx.connectors.models import Document, SlimDocument
from onyx.connectors.registry import CONNECTOR_CLASS_MAP
from tests.unit.onyx.connectors.utils import (
    load_everything_from_checkpoint_connector,
)

RawIssueFactory = Callable[..., dict[str, Any]]

# Points in time far apart enough for a single slim retrieval pass.
_START: SecondsSinceUnixEpoch = 0
_END: SecondsSinceUnixEpoch = time.time()


def _load_documents(
    connector: JiraServiceManagementConnector,
) -> list[Document]:
    outputs = load_everything_from_checkpoint_connector(connector, _START, _END)
    return [
        item
        for output in outputs
        for item in output.items
        if isinstance(item, Document)
    ]


def test_jira_source_attributes() -> None:
    """The subclass only overrides the source tag; the base keeps Jira."""
    assert JiraConnector.jira_source == DocumentSource.JIRA
    assert (
        JiraServiceManagementConnector.jira_source
        == DocumentSource.JIRA_SERVICE_MANAGEMENT
    )


def test_registry_maps_jira_service_management() -> None:
    """The registry resolves the new source to the subclass and its config."""
    mapping = CONNECTOR_CLASS_MAP[DocumentSource.JIRA_SERVICE_MANAGEMENT]
    assert mapping.module_path == ("onyx.connectors.jira_service_management.connector")
    assert mapping.class_name == "JiraServiceManagementConnector"
    assert mapping.config_class is JiraServiceManagementConnectorConfig

    connector_class = identify_connector_class(DocumentSource.JIRA_SERVICE_MANAGEMENT)
    assert connector_class is JiraServiceManagementConnector


def test_config_model_matches_jira_settings() -> None:
    """The same settings the Jira form sends validate for JSM unchanged."""
    config = JiraServiceManagementConnectorConfig.model_validate(
        {
            "jira_base_url": "https://example.atlassian.net",
            "project_key": "HELP",
            "comment_email_blacklist": ["bot@example.com"],
            "jql_query": None,
        }
    )

    assert config.jira_base_url == "https://example.atlassian.net"
    assert config.project_key == "HELP"


def test_load_credentials_labels_source_type(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    """Credentials are stored under the JSM source, not plain Jira."""
    credentials = {
        "jira_user_email": "user@example.com",
        "jira_api_token": "token123",
    }

    result = jsm_connector.load_credentials(credentials)

    assert result is None
    provider = jsm_connector.source_operations.credentials_provider
    # The provider records the source the credential belongs to.
    assert (
        provider._connector_name  # noqa: SLF001
        == DocumentSource.JIRA_SERVICE_MANAGEMENT.value
    )
    assert provider.get_credentials() == credentials


def test_load_from_checkpoint_tags_documents_jira_service_management(
    jsm_connector: JiraServiceManagementConnector,
    mock_source_operations: MagicMock,
    create_mock_issue: RawIssueFactory,
) -> None:
    """Indexed requests carry the JSM source and Jira document shape."""
    mock_source_operations.search_issues.side_effect = [
        [
            create_mock_issue(key="HELP-1", summary="Cannot log in"),
            create_mock_issue(key="HELP-2", summary="Request new laptop"),
        ],
        [create_mock_issue(key="HELP-3", summary="VPN setup")],
        [],
    ]

    documents = _load_documents(jsm_connector)

    assert [document.id for document in documents] == [
        "https://jira.example.com/browse/HELP-1",
        "https://jira.example.com/browse/HELP-2",
        "https://jira.example.com/browse/HELP-3",
    ]
    assert all(
        document.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
        for document in documents
    )
    first = documents[0]
    assert first.semantic_identifier == "HELP-1: Cannot log in"
    assert first.metadata["project"] == "HELP"
    assert first.metadata["issuetype"] == "Service Request"


def test_plain_jira_connector_still_tags_documents_jira(
    jira_base_url: str,
    mock_source_operations: MagicMock,
    create_mock_issue: RawIssueFactory,
) -> None:
    """Parameterizing the source did not disturb the plain Jira connector."""
    connector = JiraConnector(jira_base_url=jira_base_url, project_key="DEV")
    connector._source_operations = mock_source_operations
    mock_source_operations.search_issues.side_effect = [
        [create_mock_issue(key="DEV-1", project_key="DEV")],
        [],
    ]

    outputs = load_everything_from_checkpoint_connector(connector, _START, _END)
    documents = [
        item
        for output in outputs
        for item in output.items
        if isinstance(item, Document)
    ]

    assert len(documents) == 1
    assert documents[0].source == DocumentSource.JIRA


def test_retrieve_all_slim_docs_uses_jira_pipeline(
    jsm_connector: JiraServiceManagementConnector,
    mock_source_operations: MagicMock,
    create_mock_issue: RawIssueFactory,
) -> None:
    """The slim (pruning) path lists the same requests by URL."""
    mock_source_operations.search_issues.side_effect = [
        [
            create_mock_issue(key="HELP-1"),
            create_mock_issue(key="HELP-2"),
        ],
        [],
    ]

    slim_batches = list(jsm_connector.retrieve_all_slim_docs(start=_START, end=_END))
    slim_documents = [
        slim_doc
        for batch in slim_batches
        for slim_doc in batch
        if isinstance(slim_doc, SlimDocument)
    ]

    assert [slim_doc.id for slim_doc in slim_documents] == [
        "https://jira.example.com/browse/HELP-1",
        "https://jira.example.com/browse/HELP-2",
    ]
