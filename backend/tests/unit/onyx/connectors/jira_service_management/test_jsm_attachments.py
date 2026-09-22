"""Attachment parity tests for the JSM connector.

Covers the acceptance matrix required by the connector-guide contract
(`backend/onyx/connectors/README.md`, `include_attachments`):

1. the flag defaults to False and makes no attachment API calls
2. enabling it indexes attachment documents in the main pass
3. the slim pass admits exactly the same attachment IDs (full/slim parity)
4. duplicate filenames produce distinct, stable IDs
5. a broken attachment fails in isolation without losing the ticket
   (or its sibling attachments)
"""

import time
from collections.abc import Callable, Generator
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest
from jira import JIRA

from onyx.access.models import ExternalAccess
from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import SlimDocument
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)
from onyx.connectors.jira_service_management.utils import JsmFieldMap
from onyx.connectors.models import ConnectorFailure, Document
from tests.unit.onyx.connectors.jira_service_management.conftest import (
    TEST_BASE_URL,
    TEST_PROJECT_KEY,
    make_mock_jsm_issue,
)
from tests.unit.onyx.connectors.utils import (
    load_everything_from_checkpoint_connector,
)

TICKET_DOC_ID = f"{TEST_BASE_URL}/browse/HELP-101"


class MockAttachment:
    """Minimal stand-in for jira.resources.Attachment."""

    def __init__(
        self,
        id: str,
        filename: str,
        content: bytes = b"attachment text payload",
        mime_type: str = "text/plain",
        created: str = "2026-09-01T11:00:00.000+0000",
        raise_on_get: Exception | None = None,
    ) -> None:
        self.id = id
        self.filename = filename
        self.size = len(content)
        self.mimeType = mime_type
        self.created = created
        self.content = f"{TEST_BASE_URL}/secure/attachment/{id}/{filename}"
        self._content_bytes = content
        self._raise_on_get = raise_on_get

    def get(self) -> bytes:
        if self._raise_on_get is not None:
            raise self._raise_on_get
        return self._content_bytes


# Minimal stand-in for the ExternalAccess returned by project-permission
# resolution in the permission-sync path.
_TEST_PROJECT_ACCESS = ExternalAccess(
    external_user_emails=set(),
    external_user_group_ids=set(),
    is_public=True,
)


def _wire_attachment_fetch(
    mock_jira_client: MagicMock,
    attachments: list[MockAttachment],
) -> None:
    fetched_issue = MagicMock()
    fetched_issue.fields.attachment = attachments
    mock_jira_client.issue = MagicMock(return_value=fetched_issue)


def _make_connector_with_attachments(
    make_jsm_connector: Callable[..., JiraServiceManagementConnector],
    mock_jira_client: MagicMock,
    attachments: list[MockAttachment],
    include_attachments: bool = True,
    include_permissions: bool = False,
) -> JiraServiceManagementConnector:
    connector = make_jsm_connector(include_attachments=include_attachments)
    _wire_attachment_fetch(mock_jira_client, attachments)
    if include_permissions:
        # Short-circuit project-permission resolution: these tests cover
        # slim-pass propagation, not the admin-gated permission lookup.
        connector._project_permissions_cache = {
            f"{TEST_PROJECT_KEY}:unprefixed": _TEST_PROJECT_ACCESS
        }
    # Parity tracking is per-run state; make every test start clean.
    connector._attachment_admission_failures.clear()
    connector._failed_attachment_doc_ids.clear()
    return connector


@pytest.fixture
def mock_extract() -> Any:
    """Deterministic text extraction: these tests cover the connector's own
    logic (IDs, parity, isolation), not onyx's file-parsing internals."""
    with patch(
        "onyx.connectors.jira_service_management.connector.extract_file_text"
    ) as mock:
        mock.side_effect = lambda _file, file_name, **_kw: f"extracted:{file_name}"
        yield mock


class TestIncludeAttachmentsDefault:
    def test_defaults_to_false_and_makes_no_attachment_calls(
        self,
        make_jsm_connector: Callable[..., JiraServiceManagementConnector],
        mock_jira_client: MagicMock,
    ) -> None:
        connector = make_jsm_connector()
        assert connector.include_attachments is False

        issue = make_mock_jsm_issue()
        ticket_doc_id = f"{TEST_BASE_URL}/browse/{issue.key}"

        # Both passes must admit nothing while the flag is off...
        assert connector._process_issue_attachments(
            issue=issue,
            parent_hierarchy_raw_node_id=None,
            ticket_document_id=ticket_doc_id,
        ) == []
        assert connector._process_issue_attachments_slim(
            issue=issue,
            parent_hierarchy_raw_node_id=None,
            ticket_document_id=ticket_doc_id,
        ) == []

        # ...and without touching the attachment API at all.
        mock_jira_client.issue.assert_not_called()


class TestAttachmentIndexing:
    @pytest.mark.usefixtures("mock_extract")
    def test_attachments_indexed_in_main_and_slim_pass(
        self,
        make_jsm_connector: Callable[..., JiraServiceManagementConnector],
        mock_jira_client: MagicMock,
    ) -> None:
        attachments = [
            MockAttachment(id="1001", filename="server-log.txt"),
            MockAttachment(id="1002", filename="screenshot.png", content=b"png-bytes"),
        ]
        connector = _make_connector_with_attachments(
            make_jsm_connector, mock_jira_client, attachments
        )
        issue = make_mock_jsm_issue()
        ticket_doc_id = f"{TEST_BASE_URL}/browse/{issue.key}"

        main_outputs = connector._process_issue_attachments(
            issue=issue,
            parent_hierarchy_raw_node_id=TEST_PROJECT_KEY,
            ticket_document_id=ticket_doc_id,
        )

        # No failures: every attachment produced a document
        documents = [out for out in main_outputs if isinstance(out, Document)]
        assert len(documents) == 2
        assert not any(isinstance(out, ConnectorFailure) for out in main_outputs)

        first = documents[0]
        assert first.id == f"{ticket_doc_id}/attachment/1001"
        assert first.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
        assert first.semantic_identifier == "HELP-101 attachment: server-log.txt"
        # Attachment content is extracted into text sections
        assert any("extracted:server-log.txt" in s.text for s in first.sections)
        # Attachments are children of their ticket in the hierarchy
        assert first.parent_hierarchy_raw_node_id == TEST_PROJECT_KEY

        # Full/slim parity: the slim pass admits exactly the same IDs
        slim_docs = connector._process_issue_attachments_slim(
            issue=issue,
            parent_hierarchy_raw_node_id=TEST_PROJECT_KEY,
            ticket_document_id=ticket_doc_id,
        )
        assert {doc.id for doc in documents} == {sd.id for sd in slim_docs}
        assert all(isinstance(sd, SlimDocument) for sd in slim_docs)

    @pytest.mark.usefixtures("mock_extract")
    def test_duplicate_filenames_get_distinct_stable_ids(
        self,
        make_jsm_connector: Callable[..., JiraServiceManagementConnector],
        mock_jira_client: MagicMock,
    ) -> None:
        attachments = [
            MockAttachment(id="2001", filename="notes.txt"),
            MockAttachment(id="2002", filename="notes.txt"),
        ]
        connector = _make_connector_with_attachments(
            make_jsm_connector, mock_jira_client, attachments
        )
        issue = make_mock_jsm_issue()
        ticket_doc_id = f"{TEST_BASE_URL}/browse/{issue.key}"

        main_outputs = connector._process_issue_attachments(
            issue=issue,
            parent_hierarchy_raw_node_id=None,
            ticket_document_id=ticket_doc_id,
        )
        ids = [out.id for out in main_outputs if isinstance(out, Document)]

        # Identity comes from the stable attachment ID, not the filename
        assert ids == [
            f"{ticket_doc_id}/attachment/2001",
            f"{ticket_doc_id}/attachment/2002",
        ]
        assert len(set(ids)) == 2

        # Re-running yields the same IDs (stability across syncs)
        rerun_ids = [
            out.id
            for out in connector._process_issue_attachments(
                issue=issue,
                parent_hierarchy_raw_node_id=None,
                ticket_document_id=ticket_doc_id,
            )
            if isinstance(out, Document)
        ]
        assert rerun_ids == ids

    def test_disabling_the_flag_admits_nothing(
        self,
        make_jsm_connector: Callable[..., JiraServiceManagementConnector],
        mock_jira_client: MagicMock,
    ) -> None:
        # Verifies the flag-off steady state: with include_attachments=False
        # from the start, neither pass ever admits attachment IDs, so a
        # later full sync prunes any attachments indexed while the flag was
        # on. (The true->false transition itself is exercised by the full
        # indexing + pruning pipeline, not by unit-level calls like these.)
        attachments = [MockAttachment(id="3001", filename="old-report.pdf")]
        connector = _make_connector_with_attachments(
            make_jsm_connector,
            mock_jira_client,
            attachments,
            include_attachments=False,
        )
        issue = make_mock_jsm_issue()
        ticket_doc_id = f"{TEST_BASE_URL}/browse/{issue.key}"

        assert connector.include_attachments is False
        assert connector._process_issue_attachments(
            issue=issue,
            parent_hierarchy_raw_node_id=None,
            ticket_document_id=ticket_doc_id,
        ) == []
        assert connector._process_issue_attachments_slim(
            issue=issue,
            parent_hierarchy_raw_node_id=None,
            ticket_document_id=ticket_doc_id,
        ) == []


class TestAttachmentFailureIsolation:
    @pytest.mark.usefixtures("mock_extract")
    def test_broken_attachment_fails_alone_ticket_and_siblings_survive(
        self,
        make_jsm_connector: Callable[..., JiraServiceManagementConnector],
        mock_jira_client: MagicMock,
    ) -> None:
        attachments = [
            MockAttachment(
                id="4001",
                filename="corrupt.bin",
                raise_on_get=RuntimeError("download exploded"),
            ),
            MockAttachment(id="4002", filename="healthy.txt"),
        ]
        connector = _make_connector_with_attachments(
            make_jsm_connector, mock_jira_client, attachments
        )
        issue = make_mock_jsm_issue()
        ticket_doc_id = f"{TEST_BASE_URL}/browse/{issue.key}"

        outputs = connector._process_issue_attachments(
            issue=issue,
            parent_hierarchy_raw_node_id=None,
            ticket_document_id=ticket_doc_id,
        )

        failures = [out for out in outputs if isinstance(out, ConnectorFailure)]
        documents = [out for out in outputs if isinstance(out, Document)]

        # The broken attachment surfaces as an isolated failure...
        assert len(failures) == 1
        assert failures[0].failed_document.document_id == (
            f"{ticket_doc_id}/attachment/4001"
        )
        assert isinstance(failures[0].exception, RuntimeError)
        # ...the sibling is still indexed...
        assert [doc.id for doc in documents] == [
            f"{ticket_doc_id}/attachment/4002"
        ]
        # ...and the ticket itself was never part of this output at all
        assert all(doc.id != ticket_doc_id for doc in documents)

    def test_attachment_listing_failure_is_recorded_for_the_whole_set(
        self,
        make_jsm_connector: Callable[..., JiraServiceManagementConnector],
        mock_jira_client: MagicMock,
    ) -> None:
        connector = _make_connector_with_attachments(
            make_jsm_connector, mock_jira_client, []
        )
        mock_jira_client.issue = MagicMock(side_effect=RuntimeError("jira down"))
        issue = make_mock_jsm_issue()
        ticket_doc_id = f"{TEST_BASE_URL}/browse/{issue.key}"

        outputs = connector._process_issue_attachments(
            issue=issue,
            parent_hierarchy_raw_node_id=None,
            ticket_document_id=ticket_doc_id,
        )

        assert len(outputs) == 1
        failure = outputs[0]
        assert isinstance(failure, ConnectorFailure)
        assert failure.failed_document.document_id == (
            f"{ticket_doc_id}/attachments"
        )

    def test_slim_pass_stays_empty_after_listing_failure_parity(
        self,
        make_jsm_connector: Callable[..., JiraServiceManagementConnector],
        mock_jira_client: MagicMock,
    ) -> None:
        connector = _make_connector_with_attachments(
            make_jsm_connector, mock_jira_client, []
        )
        issue = make_mock_jsm_issue()
        ticket_doc_id = f"{TEST_BASE_URL}/browse/{issue.key}"

        # Main pass: listing fails -> one failure for the set, no IDs.
        main_outputs = connector._process_issue_attachments(
            issue=issue,
            parent_hierarchy_raw_node_id=None,
            ticket_document_id=ticket_doc_id,
        )
        assert [out for out in main_outputs if isinstance(out, Document)] == []

        # Slim pass must mirror that emptiness instead of re-listing: a
        # fresh enumeration could succeed here and admit IDs the main pass
        # never indexed (chunk_count IS NULL rows), or — on a later full
        # sync whose listing fails again — prune healthy attachments.
        assert connector._process_issue_attachments_slim(
            issue=issue,
            parent_hierarchy_raw_node_id=None,
            ticket_document_id=ticket_doc_id,
        ) == []

    def test_slim_pass_admits_only_attachments_that_produced_documents(
        self,
        make_jsm_connector: Callable[..., JiraServiceManagementConnector],
        mock_jira_client: MagicMock,
    ) -> None:
        attachments = [
            MockAttachment(
                id="6001",
                filename="broken.bin",
                raise_on_get=RuntimeError("download failed"),
            ),
            MockAttachment(id="6002", filename="healthy.txt"),
        ]
        connector = _make_connector_with_attachments(
            make_jsm_connector, mock_jira_client, attachments
        )
        issue = make_mock_jsm_issue()
        ticket_doc_id = f"{TEST_BASE_URL}/browse/{issue.key}"

        outputs = connector._process_issue_attachments(
            issue=issue,
            parent_hierarchy_raw_node_id=None,
            ticket_document_id=ticket_doc_id,
        )
        main_ids = {out.id for out in outputs if isinstance(out, Document)}
        assert main_ids == {f"{ticket_doc_id}/attachment/6002"}

        # Parity: the failed attachment's ID is not admitted in the slim
        # pass, so no chunk_count IS NULL row can be created for it.
        slim_docs = connector._process_issue_attachments_slim(
            issue=issue,
            parent_hierarchy_raw_node_id=None,
            ticket_document_id=ticket_doc_id,
        )
        assert [sd.id for sd in slim_docs] == [
            f"{ticket_doc_id}/attachment/6002"
        ]


class TestSlimPermissionPropagation:
    def test_perm_sync_slim_docs_carry_project_access(
        self,
        make_jsm_connector: Callable[..., JiraServiceManagementConnector],
        mock_jira_client: MagicMock,
    ) -> None:
        attachments = [MockAttachment(id="7001", filename="perm.txt")]
        connector = _make_connector_with_attachments(
            make_jsm_connector,
            mock_jira_client,
            attachments,
            include_permissions=True,
        )
        issue = make_mock_jsm_issue()
        ticket_doc_id = f"{TEST_BASE_URL}/browse/{issue.key}"

        slim_docs = connector._process_issue_attachments_slim(
            issue=issue,
            parent_hierarchy_raw_node_id=None,
            ticket_document_id=ticket_doc_id,
            include_permissions=True,
            project_key=TEST_PROJECT_KEY,
        )
        assert len(slim_docs) == 1
        assert slim_docs[0].external_access == _TEST_PROJECT_ACCESS

    def test_indexing_path_slim_docs_have_no_permissions(
        self,
        make_jsm_connector: Callable[..., JiraServiceManagementConnector],
        mock_jira_client: MagicMock,
    ) -> None:
        attachments = [MockAttachment(id="7002", filename="noperm.txt")]
        connector = _make_connector_with_attachments(
            make_jsm_connector, mock_jira_client, attachments
        )
        issue = make_mock_jsm_issue()
        ticket_doc_id = f"{TEST_BASE_URL}/browse/{issue.key}"

        slim_docs = connector._process_issue_attachments_slim(
            issue=issue,
            parent_hierarchy_raw_node_id=None,
            ticket_document_id=ticket_doc_id,
        )
        assert len(slim_docs) == 1
        assert slim_docs[0].external_access is None


class TestEmptyAttachmentContent:
    @pytest.mark.usefixtures("mock_extract")
    def test_zero_byte_attachment_fails_instead_of_empty_document(
        self,
        make_jsm_connector: Callable[..., JiraServiceManagementConnector],
        mock_jira_client: MagicMock,
    ) -> None:
        attachments = [
            MockAttachment(id="8001", filename="empty.bin", content=b""),
            MockAttachment(id="8002", filename="real.txt"),
        ]
        connector = _make_connector_with_attachments(
            make_jsm_connector, mock_jira_client, attachments
        )
        issue = make_mock_jsm_issue()
        ticket_doc_id = f"{TEST_BASE_URL}/browse/{issue.key}"

        outputs = connector._process_issue_attachments(
            issue=issue,
            parent_hierarchy_raw_node_id=None,
            ticket_document_id=ticket_doc_id,
        )
        failures = [out for out in outputs if isinstance(out, ConnectorFailure)]
        documents = [out for out in outputs if isinstance(out, Document)]
        assert [f.failed_document.document_id for f in failures] == [
            f"{ticket_doc_id}/attachment/8001"
        ]
        assert [d.id for d in documents] == [
            f"{ticket_doc_id}/attachment/8002"
        ]

        # Parity holds for the surviving attachment only.
        slim_docs = connector._process_issue_attachments_slim(
            issue=issue,
            parent_hierarchy_raw_node_id=None,
            ticket_document_id=ticket_doc_id,
        )
        assert [sd.id for sd in slim_docs] == [
            f"{ticket_doc_id}/attachment/8002"
        ]


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


class TestAttachmentsThroughPipeline:
    @pytest.mark.usefixtures("mock_extract")
    def test_attachments_flow_through_checkpointed_pipeline(
        self,
        jsm_connector: JiraServiceManagementConnector,
    ) -> None:
        connector = jsm_connector
        connector.include_attachments = True

        issue = make_mock_jsm_issue(key="HELP-101")
        jira_client = cast(JIRA, connector._jira_client)
        search_issues_mock = cast(MagicMock, jira_client.search_issues)
        search_issues_mock.side_effect = [[issue]]

        fetched_issue = MagicMock()
        fetched_issue.fields.attachment = [
            MockAttachment(id="5001", filename="pipeline.txt")
        ]
        jira_client.issue = MagicMock(return_value=fetched_issue)

        end_time = time.time()
        outputs = load_everything_from_checkpoint_connector(
            connector, 0, end_time
        )

        # The ticket document and its attachment document both come through
        all_items = [item for output in outputs for item in output.items]
        documents = [item for item in all_items if isinstance(item, Document)]
        doc_ids = [doc.id for doc in documents]

        assert f"{TEST_BASE_URL}/browse/HELP-101" in doc_ids
        assert (
            f"{TEST_BASE_URL}/browse/HELP-101/attachment/5001" in doc_ids
        )
        # No unexpected failures
        failures = [
            item for item in all_items if isinstance(item, ConnectorFailure)
        ]
        assert failures == []

        # The slim pass mirrors the attachment ID exactly
        slim_docs = connector._process_issue_attachments_slim(
            issue=issue,
            parent_hierarchy_raw_node_id=TEST_PROJECT_KEY,
            ticket_document_id=f"{TEST_BASE_URL}/browse/HELP-101",
        )
        assert [sd.id for sd in slim_docs] == [
            f"{TEST_BASE_URL}/browse/HELP-101/attachment/5001"
        ]
