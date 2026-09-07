from collections.abc import Generator
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from jira import JIRA, JIRAError
from jira.resources import Issue, Project
from requests import ConnectionError

from onyx.configs.constants import DocumentSource
from onyx.connectors.connector_runner import CheckpointOutputWrapper
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    InsufficientPermissionsError,
    UnexpectedValidationError,
)
from onyx.connectors.interfaces import (
    CheckpointedConnectorWithPermSync,
    CheckpointOutput,
    SlimConnectorWithPermSync,
)
from onyx.connectors.jira.connector import JiraConnector, JiraConnectorCheckpoint
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)
from onyx.connectors.models import (
    ConnectorFailure,
    ConnectorMissingCredentialError,
    Document,
    DocumentFailure,
    HierarchyNode,
    SlimDocument,
    TextSection,
)
from onyx.connectors.registry import CONNECTOR_CLASS_MAP
from onyx.db.enums import HierarchyNodeType


@pytest.fixture
def client() -> MagicMock:
    client = MagicMock(spec=JIRA)
    client.project.return_value = Project(
        {}, MagicMock(), raw={"key": "HELP", "projectTypeKey": "service_desk"}
    )
    return client


@pytest.fixture
def connector(
    client: MagicMock,
) -> Generator[JiraServiceManagementConnector, None, None]:
    with patch.object(JiraConnector, "jira_client", new_callable=PropertyMock) as prop:
        prop.return_value = client
        yield JiraServiceManagementConnector("https://example.atlassian.net", " HELP ")


@pytest.mark.parametrize("key", ["", " ", "\n\t"])
def test_empty_project_is_rejected(key: str) -> None:
    with pytest.raises(ConnectorValidationError, match="project key"):
        JiraServiceManagementConnector("https://example.atlassian.net", key)


def test_credentials_are_required() -> None:
    connector = JiraServiceManagementConnector("https://example.atlassian.net", "HELP")
    with pytest.raises(ConnectorMissingCredentialError):
        connector.validate_connector_settings()


@pytest.mark.parametrize("project_type", ["software", "business", None])
def test_project_type_must_be_confirmed(
    connector: JiraServiceManagementConnector,
    client: MagicMock,
    project_type: str | None,
) -> None:
    client.project.return_value = Project(
        {}, MagicMock(), raw={"key": "HELP", "projectTypeKey": project_type}
    )
    with pytest.raises(ConnectorValidationError, match="not a Jira Service Management"):
        connector.validate_connector_settings()


@pytest.mark.parametrize(
    "status,exception",
    [
        (401, CredentialExpiredError),
        (403, InsufficientPermissionsError),
        (404, ConnectorValidationError),
        (429, ConnectorValidationError),
        (500, ConnectorValidationError),
    ],
)
def test_http_errors_fail_validation(
    connector: JiraServiceManagementConnector,
    client: MagicMock,
    status: int,
    exception: type[Exception],
) -> None:
    client.project.side_effect = JIRAError(status_code=status)
    with pytest.raises(exception):
        connector.validate_connector_settings()


def test_network_error_fails_validation(
    connector: JiraServiceManagementConnector, client: MagicMock
) -> None:
    client.project.side_effect = ConnectionError("unreachable")
    with pytest.raises(UnexpectedValidationError):
        connector.validate_connector_settings()


def test_source_conversion_preserves_checkpoint_hierarchy_and_failures(
    connector: JiraServiceManagementConnector, client: MagicMock
) -> None:
    document = Document(
        id="https://example.atlassian.net/browse/HELP-1",
        sections=[
            TextSection(
                text="Printer broken",
                link="https://example.atlassian.net/browse/HELP-1",
            )
        ],
        source=DocumentSource.JIRA,
        semantic_identifier="HELP-1",
        metadata={"project": "HELP"},
    )
    hierarchy = HierarchyNode(
        raw_node_id="HELP", display_name="Help", node_type=HierarchyNodeType.FOLDER
    )
    failure = ConnectorFailure(
        failed_document=DocumentFailure(document_id="HELP-2"),
        failure_message="Temporary ticket failure",
    )
    first = connector.build_dummy_checkpoint()
    resumed = JiraConnectorCheckpoint(has_more=True, cursor="next-page", ids_done=True)

    def page() -> CheckpointOutput[JiraConnectorCheckpoint]:
        yield hierarchy
        yield document
        yield failure
        return resumed

    with patch.object(
        connector.jira, "load_from_checkpoint", return_value=page()
    ) as load:
        output = list(
            CheckpointOutputWrapper[JiraConnectorCheckpoint]()(
                connector.load_from_checkpoint(1, 2, first)
            )
        )
    load.assert_called_once_with(1, 2, first)
    client.project.assert_called_once_with("HELP")
    assert output[0][1] is hierarchy
    converted = output[1][0]
    assert converted is not None
    assert converted.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
    assert converted.id == document.id
    assert converted.sections == document.sections
    assert document.source == DocumentSource.JIRA
    assert output[2][2] is failure
    assert output[-1][3] is resumed
    assert connector.validate_checkpoint_json(resumed.model_dump_json()) == resumed


def test_slim_scan_passes_time_range_and_heartbeat(
    connector: JiraServiceManagementConnector,
) -> None:
    documents = [SlimDocument(id="https://example.atlassian.net/browse/HELP-1")]
    heartbeat = MagicMock()
    with patch.object(
        connector.jira, "retrieve_all_slim_docs", return_value=iter([documents])
    ) as scan:
        assert list(connector.retrieve_all_slim_docs(1, 2, heartbeat)) == [documents]
    scan.assert_called_once_with(1, 2, heartbeat)


def test_invalid_project_cannot_start_indexing_or_pruning(
    connector: JiraServiceManagementConnector, client: MagicMock
) -> None:
    client.project.side_effect = JIRAError(status_code=403)
    with patch.object(connector.jira, "load_from_checkpoint") as load:
        with pytest.raises(InsufficientPermissionsError):
            list(
                connector.load_from_checkpoint(0, 1, connector.build_dummy_checkpoint())
            )
        load.assert_not_called()
    with patch.object(connector.jira, "retrieve_all_slim_docs") as slim:
        with pytest.raises(InsufficientPermissionsError):
            list(connector.retrieve_all_slim_docs())
        slim.assert_not_called()


def test_new_credentials_require_validation_again(
    connector: JiraServiceManagementConnector, client: MagicMock
) -> None:
    connector.validate_connector_settings()
    with patch.object(connector.jira, "load_credentials", return_value=None) as load:
        connector.load_credentials({"jira_api_token": "replacement-test-token"})
    load.assert_called_once_with({"jira_api_token": "replacement-test-token"})
    client.project.side_effect = JIRAError(status_code=401)
    with pytest.raises(CredentialExpiredError):
        list(connector.retrieve_all_slim_docs())


def test_jira_project_roles_are_not_advertised_as_jsm_permission_sync(
    connector: JiraServiceManagementConnector,
) -> None:
    assert not isinstance(connector, CheckpointedConnectorWithPermSync)
    assert not isinstance(connector, SlimConnectorWithPermSync)


def test_connector_is_registered() -> None:
    mapping = CONNECTOR_CLASS_MAP[DocumentSource.JIRA_SERVICE_MANAGEMENT]
    assert mapping.module_path == JiraServiceManagementConnector.__module__
    assert mapping.class_name == JiraServiceManagementConnector.__name__


@pytest.mark.parametrize("description", ["Please help", None, " \n"])
def test_real_jira_pipeline_keeps_project_scope_across_pages(
    connector: JiraServiceManagementConnector,
    client: MagicMock,
    description: str | None,
) -> None:
    client._options = {"rest_api_version": "2"}
    issues = [
        Issue(
            {},
            MagicMock(),
            raw={
                "key": f"HELP-{number}",
                "fields": {
                    "summary": f"Request {number}",
                    "description": description,
                    "labels": [],
                    "comment": {"comments": []},
                    "created": "2026-01-01T00:00:00.000+0000",
                    "updated": "2026-01-02T00:00:00.000+0000",
                    "project": {"key": "HELP", "name": "Help desk"},
                    "issuetype": {"name": "Service Request"},
                },
            },
        )
        for number in (1, 2)
    ]
    client.search_issues.side_effect = [[issues[0]], [issues[1]], []]
    checkpoint = connector.build_dummy_checkpoint()
    documents: list[Document] = []
    with patch("onyx.connectors.jira.connector._JIRA_FULL_PAGE_SIZE", 1):
        for _ in range(3):
            for document, _, failure, next_checkpoint in CheckpointOutputWrapper[
                JiraConnectorCheckpoint
            ]()(connector.load_from_checkpoint(0, 1_800_000_000, checkpoint)):
                assert failure is None
                if document is not None:
                    documents.append(document)
                if next_checkpoint is not None:
                    checkpoint = connector.validate_checkpoint_json(
                        next_checkpoint.model_dump_json()
                    )

    assert not checkpoint.has_more
    assert [document.semantic_identifier for document in documents] == [
        "HELP-1: Request 1",
        "HELP-2: Request 2",
    ]
    assert all(
        document.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
        for document in documents
    )
    assert all(document.metadata["project"] == "HELP" for document in documents)
    for document in documents:
        assert document.sections[0].link == document.id
        expected_text = description.strip() if description else ""
        section_text = document.sections[0].text
        assert section_text is not None
        assert section_text.strip() == (expected_text or document.semantic_identifier)
    assert [call.kwargs["startAt"] for call in client.search_issues.call_args_list] == [
        0,
        1,
        2,
    ]
    assert all(
        'project = "HELP"' in call.kwargs["jql_str"]
        for call in client.search_issues.call_args_list
    )
    client.project.assert_called_once_with("HELP")
