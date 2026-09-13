import time
from collections.abc import Callable, Generator
from typing import cast
from unittest.mock import MagicMock, patch

import pytest
from jira import JIRA, JIRAError

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
    SlimConnector,
    SlimConnectorWithPermSync,
)
from onyx.connectors.jira.connector import JiraConnector, JiraConnectorCheckpoint
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)
from onyx.connectors.jira_service_management.utils import (
    FIELD_CUSTOMER_REQUEST_TYPE,
    FIELD_ORGANIZATIONS,
    FIELD_SLA_STATUS,
    JsmFieldMap,
)
from onyx.connectors.models import (
    ConnectorFailure,
    ConnectorMissingCredentialError,
    Document,
    HierarchyNode,
    SlimDocument,
    TextSection,
)
from tests.unit.onyx.connectors.jira_service_management.conftest import (
    ORGANIZATIONS_FIELD_ID,
    REQUEST_TYPE_FIELD_ID,
    SLA_FIRST_RESPONSE_FIELD_ID,
    SLA_RESOLUTION_FIELD_ID,
    TEST_BASE_URL,
    TEST_PROJECT_KEY,
    make_mock_jsm_issue,
)
from tests.unit.onyx.connectors.utils import (
    load_everything_from_checkpoint_connector,
)

PAGE_SIZE = 2


@pytest.fixture
def jsm_connector(
    make_jsm_connector: Callable[..., JiraServiceManagementConnector],
    jsm_field_map: JsmFieldMap,
) -> Generator[JiraServiceManagementConnector, None, None]:
    """Connector with JSM field discovery short-circuited for determinism."""
    connector = make_jsm_connector()
    connector._jsm_field_map = jsm_field_map
    jira_client = cast(JIRA, connector._jira_client)
    jira_client._options = MagicMock()
    with patch("onyx.connectors.jira.connector._JIRA_FULL_PAGE_SIZE", 2):
        yield connector


class TestProcessIssue:
    def test_process_issue_full_jsm_metadata(
        self, jsm_connector: JiraServiceManagementConnector
    ) -> None:
        issue = make_mock_jsm_issue(
            organizations=["Acme Corp", "Beta LLC"],
            slas={
                SLA_FIRST_RESPONSE_FIELD_ID: {
                    "name": "Time to first response",
                    "completedCycles": [{"breached": False}],
                },
                SLA_RESOLUTION_FIELD_ID: {
                    "name": "Time to resolution",
                    "ongoingCycle": {"breached": False},
                },
            },
        )

        document = jsm_connector._process_issue(issue)
        assert document is not None

        assert document.id == f"{TEST_BASE_URL}/browse/HELP-101"
        assert document.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
        assert document.semantic_identifier == "HELP-101: VPN not connecting"
        assert document.title == "HELP-101 VPN not connecting"

        # Standard Jira metadata is preserved
        assert document.metadata["key"] == "HELP-101"
        assert document.metadata["status"] == "Waiting for support"
        assert document.metadata["priority"] == "High"
        assert document.metadata["project"] == TEST_PROJECT_KEY
        assert document.metadata["project_name"] == "IT Help Desk"

        # JSM specific metadata
        assert document.metadata[FIELD_CUSTOMER_REQUEST_TYPE] == "Get IT help"
        assert document.metadata[FIELD_ORGANIZATIONS] == ["Acme Corp", "Beta LLC"]
        assert document.metadata[FIELD_SLA_STATUS] == [
            "Time to first response: Met",
            "Time to resolution: In Progress",
        ]

        # Content: description plus public comment; internal note excluded by default
        assert len(document.sections) == 1
        section = document.sections[0]
        assert isinstance(section, TextSection)
        text = section.text
        assert "Unable to connect to the corporate VPN." in text
        assert "Have you tried restarting your laptop?" in text
        assert "Checked the VPN gateway logs; cert expired." not in text

    def test_process_issue_includes_internal_comments_when_enabled(
        self, make_jsm_connector: Callable[..., JiraServiceManagementConnector]
    ) -> None:
        connector = make_jsm_connector(include_internal_comments=True)
        connector._jsm_field_map = JsmFieldMap()
        issue = make_mock_jsm_issue()

        document = connector._process_issue(issue)
        assert document is not None
        section = document.sections[0]
        assert isinstance(section, TextSection)
        text = section.text
        assert "Have you tried restarting your laptop?" in text
        assert "[Internal Note] Checked the VPN gateway logs; cert expired." in text

    def test_process_issue_comment_email_blacklist(
        self, make_jsm_connector: Callable[..., JiraServiceManagementConnector]
    ) -> None:
        connector = make_jsm_connector(
            comment_email_blacklist=["bob@example.com"],
            include_internal_comments=True,
        )
        connector._jsm_field_map = JsmFieldMap()
        issue = make_mock_jsm_issue()

        document = connector._process_issue(issue)
        assert document is not None
        section = document.sections[0]
        assert isinstance(section, TextSection)
        text = section.text
        # All comments are authored by bob@example.com
        assert "Have you tried restarting your laptop?" not in text
        assert "Checked the VPN gateway logs; cert expired." not in text

    def test_process_issue_skips_labeled_tickets(
        self, jsm_connector: JiraServiceManagementConnector
    ) -> None:
        jsm_connector.labels_to_skip = {"sensitive"}
        issue = make_mock_jsm_issue(labels=["vpn", "sensitive"])
        assert jsm_connector._process_issue(issue) is None

    def test_process_issue_skips_oversized_tickets(
        self, jsm_connector: JiraServiceManagementConnector
    ) -> None:
        issue = make_mock_jsm_issue(description="way too big " * 10)
        with patch("onyx.connectors.jira.connector.JIRA_CONNECTOR_MAX_TICKET_SIZE", 10):
            assert jsm_connector._process_issue(issue) is None

    def test_process_issue_structural_fallback_without_field_map(
        self, make_jsm_connector: Callable[..., JiraServiceManagementConnector]
    ) -> None:
        """When field discovery fails, structure-based detection still works."""
        connector = make_jsm_connector()
        connector._jsm_field_map = JsmFieldMap()  # discovery produced nothing

        issue = make_mock_jsm_issue(
            request_type=None,
            organizations=None,
            field_map=JsmFieldMap(),
            raw_overrides={
                # request type embedded in an object (no known field ID)
                "customfield_99999": {
                    "requestType": {"name": "Report a security issue"}
                },
                # organizations shaped as {"id", "name"} pairs (no known field ID)
                "customfield_88888": [
                    {"id": "1", "name": "Globex"},
                ],
                SLA_FIRST_RESPONSE_FIELD_ID: {
                    "name": "Time to first response",
                    "ongoingCycle": {"breached": True},
                },
            },
        )

        document = connector._process_issue(issue)
        assert document is not None
        assert document.metadata[FIELD_CUSTOMER_REQUEST_TYPE] == (
            "Report a security issue"
        )
        assert document.metadata[FIELD_ORGANIZATIONS] == ["Globex"]
        assert document.metadata[FIELD_SLA_STATUS] == [
            "Time to first response: Breached"
        ]

    def test_process_issue_structural_fallback_ignores_non_org_lists(
        self, make_jsm_connector: Callable[..., JiraServiceManagementConnector]
    ) -> None:
        """Lists of dicts with extra keys (e.g. components) are not organizations."""
        connector = make_jsm_connector()
        connector._jsm_field_map = JsmFieldMap()

        issue = make_mock_jsm_issue(
            request_type=None,
            organizations=None,
            field_map=JsmFieldMap(),
            raw_overrides={
                "components": [{"id": "1", "name": "Backend", "description": "API"}],
            },
        )

        document = connector._process_issue(issue)
        assert document is not None
        assert FIELD_ORGANIZATIONS not in document.metadata

    def test_process_issue_hierarchy_parent_passthrough(
        self, jsm_connector: JiraServiceManagementConnector
    ) -> None:
        issue = make_mock_jsm_issue()
        document = jsm_connector._process_issue(issue, "HELP")
        assert document is not None
        assert document.parent_hierarchy_raw_node_id == "HELP"

    def test_process_issue_completed_sla_breached(
        self, jsm_connector: JiraServiceManagementConnector
    ) -> None:
        issue = make_mock_jsm_issue(
            request_type=None,
            organizations=None,
            slas={
                SLA_RESOLUTION_FIELD_ID: {
                    "name": "Time to resolution",
                    "completedCycles": [{"breached": True}],
                },
            },
        )
        document = jsm_connector._process_issue(issue)
        assert document is not None
        assert document.metadata[FIELD_SLA_STATUS] == ["Time to resolution: Breached"]


class TestFieldDiscovery:
    def test_discover_jsm_fields_by_name(self, mock_jira_client: MagicMock) -> None:
        mock_jira_client.fields.return_value = [
            {"id": "summary", "name": "Summary", "custom": False},
            {"id": REQUEST_TYPE_FIELD_ID, "name": "Customer Request Type"},
            {"id": ORGANIZATIONS_FIELD_ID, "name": "Organizations"},
            {"id": "customfield_10002", "name": "Satisfaction"},
        ]

        connector = JiraServiceManagementConnector(
            jira_base_url=TEST_BASE_URL, project_key=TEST_PROJECT_KEY
        )
        connector._jira_client = mock_jira_client

        field_map = connector.jsm_field_map
        assert field_map.customer_request_type == REQUEST_TYPE_FIELD_ID
        assert field_map.organizations == ORGANIZATIONS_FIELD_ID

        # cached: fields() is only fetched once
        assert connector.jsm_field_map == field_map
        assert mock_jira_client.fields.call_count == 1

    def test_discover_jsm_fields_api_failure_falls_back(
        self, mock_jira_client: MagicMock
    ) -> None:
        mock_jira_client.fields.side_effect = RuntimeError("403")

        connector = JiraServiceManagementConnector(
            jira_base_url=TEST_BASE_URL, project_key=TEST_PROJECT_KEY
        )
        connector._jira_client = mock_jira_client

        field_map = connector.jsm_field_map
        assert field_map.customer_request_type is None
        assert field_map.organizations is None


class TestCheckpointing:
    def test_load_from_checkpoint_happy_path(
        self, jsm_connector: JiraServiceManagementConnector
    ) -> None:
        mock_issue1 = make_mock_jsm_issue(key="HELP-1", summary="Issue 1")
        mock_issue2 = make_mock_jsm_issue(key="HELP-2", summary="Issue 2")
        mock_issue3 = make_mock_jsm_issue(key="HELP-3", summary="Issue 3")

        jira_client = cast(JIRA, jsm_connector._jira_client)
        search_issues_mock = cast(MagicMock, jira_client.search_issues)
        search_issues_mock.side_effect = [
            [mock_issue1, mock_issue2],
            [mock_issue3],
        ]

        end_time = time.time()
        outputs = load_everything_from_checkpoint_connector(jsm_connector, 0, end_time)

        assert len(outputs) == 2

        checkpoint_output1 = outputs[0]
        assert len(checkpoint_output1.items) == 2
        document1 = checkpoint_output1.items[0]
        assert isinstance(document1, Document)
        assert document1.id == f"{TEST_BASE_URL}/browse/HELP-1"
        assert document1.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
        document2 = checkpoint_output1.items[1]
        assert isinstance(document2, Document)
        assert document2.id == f"{TEST_BASE_URL}/browse/HELP-2"
        assert checkpoint_output1.next_checkpoint == JiraConnectorCheckpoint(
            offset=2,
            has_more=True,
            seen_hierarchy_node_ids=[TEST_PROJECT_KEY],
        )

        checkpoint_output2 = outputs[1]
        assert len(checkpoint_output2.items) == 1
        document3 = checkpoint_output2.items[0]
        assert isinstance(document3, Document)
        assert document3.id == f"{TEST_BASE_URL}/browse/HELP-3"
        assert checkpoint_output2.next_checkpoint == JiraConnectorCheckpoint(
            offset=3,
            has_more=False,
            seen_hierarchy_node_ids=[TEST_PROJECT_KEY],
        )

        assert search_issues_mock.call_count == 2
        args, kwargs = search_issues_mock.call_args_list[0]
        assert kwargs["startAt"] == 0
        assert kwargs["maxResults"] == PAGE_SIZE

        args, kwargs = search_issues_mock.call_args_list[1]
        assert kwargs["startAt"] == 2
        assert kwargs["maxResults"] == PAGE_SIZE

    def test_load_from_checkpoint_yields_hierarchy_node(
        self, jsm_connector: JiraServiceManagementConnector
    ) -> None:
        mock_issue = make_mock_jsm_issue(key="HELP-1")

        jira_client = cast(JIRA, jsm_connector._jira_client)
        search_issues_mock = cast(MagicMock, jira_client.search_issues)
        search_issues_mock.side_effect = [[mock_issue]]

        end_time = time.time()
        checkpoint = jsm_connector.build_dummy_checkpoint()
        doc_batch_generator = CheckpointOutputWrapper[JiraConnectorCheckpoint]()(
            jsm_connector.load_from_checkpoint(0, end_time, checkpoint)
        )
        nodes: list[HierarchyNode] = []
        for document, hierarchy_node, failure, _ in doc_batch_generator:
            if hierarchy_node is not None:
                nodes.append(hierarchy_node)
            if document is not None:
                assert document.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
            assert failure is None

        assert len(nodes) == 1
        assert nodes[0].raw_node_id == TEST_PROJECT_KEY
        assert nodes[0].display_name == "IT Help Desk"

    def test_load_from_checkpoint_yields_failure_for_bad_issue(
        self, jsm_connector: JiraServiceManagementConnector
    ) -> None:
        good_issue = make_mock_jsm_issue(key="HELP-1")
        bad_issue = make_mock_jsm_issue(key="HELP-2", updated="not-a-timestamp")

        jira_client = cast(JIRA, jsm_connector._jira_client)
        search_issues_mock = cast(MagicMock, jira_client.search_issues)
        search_issues_mock.side_effect = [[good_issue, bad_issue], []]

        end_time = time.time()
        outputs = load_everything_from_checkpoint_connector(jsm_connector, 0, end_time)

        # The good ticket is still indexed, the bad one surfaces as a failure
        documents = [item for item in outputs[0].items if isinstance(item, Document)]
        failures = [
            item for item in outputs[0].items if isinstance(item, ConnectorFailure)
        ]
        assert len(documents) == 1
        assert documents[0].id == f"{TEST_BASE_URL}/browse/HELP-1"
        assert len(failures) == 1
        assert failures[0].failed_document is not None
        assert failures[0].failed_document.document_id == "HELP-2"

    def test_retrieve_all_slim_docs(
        self, jsm_connector: JiraServiceManagementConnector
    ) -> None:
        mock_issue1 = make_mock_jsm_issue(key="HELP-1")
        mock_issue2 = make_mock_jsm_issue(key="HELP-2")

        jira_client = cast(JIRA, jsm_connector._jira_client)
        search_issues_mock = cast(MagicMock, jira_client.search_issues)
        search_issues_mock.return_value = [mock_issue1, mock_issue2]

        batches = list(jsm_connector.retrieve_all_slim_docs(0, 100))

        assert len(batches) == 1
        slim_docs = [item for item in batches[0] if isinstance(item, SlimDocument)]
        assert [slim_doc.id for slim_doc in slim_docs] == [
            f"{TEST_BASE_URL}/browse/HELP-1",
            f"{TEST_BASE_URL}/browse/HELP-2",
        ]


class TestValidateConnectorSettings:
    def test_missing_credentials(self) -> None:
        connector = JiraServiceManagementConnector(
            jira_base_url=TEST_BASE_URL, project_key=TEST_PROJECT_KEY
        )
        with pytest.raises(ConnectorMissingCredentialError):
            connector.validate_connector_settings()

    def test_missing_project_key(self, mock_jira_client: MagicMock) -> None:
        connector = JiraServiceManagementConnector(
            jira_base_url=TEST_BASE_URL, project_key=""
        )
        connector._jira_client = mock_jira_client
        with pytest.raises(ConnectorValidationError, match="project key is required"):
            connector.validate_connector_settings()

    def test_rejects_non_service_desk_project(
        self, make_jsm_connector: Callable[..., JiraServiceManagementConnector]
    ) -> None:
        connector = make_jsm_connector()
        software_project = MagicMock()
        software_project.projectTypeKey = "software"
        jira_client = cast(JIRA, connector._jira_client)
        project_mock = cast(MagicMock, jira_client.project)
        project_mock.return_value = software_project

        with pytest.raises(ConnectorValidationError, match="service desk"):
            connector.validate_connector_settings()

    def test_accepts_service_desk_project(
        self, make_jsm_connector: Callable[..., JiraServiceManagementConnector]
    ) -> None:
        connector = make_jsm_connector()
        service_desk_project = MagicMock()
        service_desk_project.projectTypeKey = "service_desk"
        jira_client = cast(JIRA, connector._jira_client)
        project_mock = cast(MagicMock, jira_client.project)
        project_mock.return_value = service_desk_project

        connector.validate_connector_settings()
        project_mock.assert_called_once_with(TEST_PROJECT_KEY)

    def test_accepts_service_desk_project_via_raw(
        self, make_jsm_connector: Callable[..., JiraServiceManagementConnector]
    ) -> None:
        connector = make_jsm_connector()
        # projectTypeKey only available on the raw payload (e.g. server instances)
        project = MagicMock()
        project.raw = {"projectTypeKey": "service_desk"}
        jira_client = cast(JIRA, connector._jira_client)
        project_mock = cast(MagicMock, jira_client.project)
        project_mock.return_value = project

        connector.validate_connector_settings()

    @pytest.mark.parametrize(
        "status_code,expected_exception,expected_message",
        [
            (401, CredentialExpiredError, "expired or invalid"),
            (403, InsufficientPermissionsError, "sufficient permissions"),
            (404, UnexpectedValidationError, "Unexpected Jira error"),
            (429, ConnectorValidationError, "rate-limits"),
        ],
    )
    def test_project_lookup_error_mapping(
        self,
        make_jsm_connector: Callable[..., JiraServiceManagementConnector],
        status_code: int,
        expected_exception: type[Exception],
        expected_message: str,
    ) -> None:
        connector = make_jsm_connector()
        jira_client = cast(JIRA, connector._jira_client)
        project_mock = cast(MagicMock, jira_client.project)
        project_mock.side_effect = JIRAError(status_code=status_code)

        with pytest.raises(expected_exception) as excinfo:
            connector.validate_connector_settings()
        assert expected_message in str(excinfo.value)

    def test_jql_query_validation_failure(self, mock_jira_client: MagicMock) -> None:
        connector = JiraServiceManagementConnector(
            jira_base_url=TEST_BASE_URL,
            project_key=TEST_PROJECT_KEY,
            jql_query="issuetype = Incident",
        )
        connector._jira_client = mock_jira_client

        service_desk_project = MagicMock()
        service_desk_project.projectTypeKey = "service_desk"
        mock_jira_client.project.return_value = service_desk_project

        with patch(
            "onyx.connectors.jira_service_management.connector._perform_jql_search",
            side_effect=JIRAError(status_code=400, text="Bad JQL"),
        ):
            with pytest.raises(ConnectorValidationError, match="Bad JQL"):
                connector.validate_connector_settings()

    def test_jql_query_validation_success(self, mock_jira_client: MagicMock) -> None:
        connector = JiraServiceManagementConnector(
            jira_base_url=TEST_BASE_URL,
            project_key=TEST_PROJECT_KEY,
            jql_query="issuetype = Incident",
        )
        connector._jira_client = mock_jira_client

        service_desk_project = MagicMock()
        service_desk_project.projectTypeKey = "service_desk"
        mock_jira_client.project.return_value = service_desk_project

        with patch(
            "onyx.connectors.jira_service_management.connector._perform_jql_search",
            return_value=iter([]),
        ):
            connector.validate_connector_settings()


class TestInheritanceContract:
    def test_document_source_override(self) -> None:
        assert JiraConnector.document_source == DocumentSource.JIRA
        assert (
            JiraServiceManagementConnector.document_source
            == DocumentSource.JIRA_SERVICE_MANAGEMENT
        )

    def test_is_a_checkpointed_connector_with_perm_sync_and_slim(
        self, make_jsm_connector: Callable[..., JiraServiceManagementConnector]
    ) -> None:
        connector = make_jsm_connector()
        assert isinstance(connector, CheckpointedConnectorWithPermSync)
        assert isinstance(connector, SlimConnector)
        assert isinstance(connector, SlimConnectorWithPermSync)

        checkpoint = connector.build_dummy_checkpoint()
        assert isinstance(checkpoint, JiraConnectorCheckpoint)
        assert checkpoint.has_more is True

        assert (
            connector.validate_checkpoint_json(checkpoint.model_dump_json())
            == checkpoint
        )
