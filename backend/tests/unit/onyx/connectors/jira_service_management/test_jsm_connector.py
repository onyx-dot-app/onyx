import time
from collections.abc import Callable
from typing import cast
from unittest.mock import MagicMock

import pytest
from jira import JIRA, JIRAError

from onyx.access.models import ExternalAccess
from onyx.configs.constants import DocumentSource
from onyx.connectors.connector_runner import CheckpointOutputWrapper
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
)
from onyx.connectors.jira.connector import JiraConnectorCheckpoint
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)
from onyx.connectors.models import (
    ConnectorFailure,
    Document,
    HierarchyNode,
    SlimDocument,
)
from onyx.utils.logger import setup_logger
from tests.unit.onyx.connectors.jira_service_management.conftest import (
    create_mock_attachment,
    create_mock_comment,
)
from tests.unit.onyx.connectors.utils import (
    load_everything_from_checkpoint_connector,
)

logger = setup_logger()


def _collect_all_items(
    connector: JiraServiceManagementConnector,
    perm_sync: bool = False,
) -> list[Document | HierarchyNode | ConnectorFailure]:
    """Drain the checkpoint loop, keeping every emitted item type."""
    checkpoint = connector.build_dummy_checkpoint()
    items: list[Document | HierarchyNode | ConnectorFailure] = []
    while checkpoint.has_more:
        wrapper = CheckpointOutputWrapper[JiraConnectorCheckpoint]()
        generator = (
            connector.load_from_checkpoint_with_perm_sync(0, time.time(), checkpoint)
            if perm_sync
            else connector.load_from_checkpoint(0, time.time(), checkpoint)
        )
        for document, node, failure, _ in wrapper(generator):
            if document is not None:
                items.append(document)
            if node is not None:
                items.append(node)
            if failure is not None:
                items.append(failure)
        if wrapper.next_checkpoint is None:
            raise RuntimeError("checkpoint generator ended without checkpoint")
        checkpoint = wrapper.next_checkpoint
    return items


def test_jql_query_always_scopes_to_project(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    start, end = 0.0, 3600.0

    query = jsm_connector._get_jql_query(start, end)
    assert 'project = "IT"' in query
    assert f"updated >= {int(start * 1000)}" in query
    assert f"updated <= {int(end * 1000)}" in query


def test_jql_query_combines_custom_filter_with_project_scope(
    jira_base_url: str, project_key: str
) -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url=jira_base_url,
        project_key=project_key,
        jql_query='issuetype = "Incident"',
    )

    query = connector._get_jql_query(0.0, 3600.0)

    assert 'project = "IT"' in query
    assert '(issuetype = "Incident")' in query
    assert " AND " in query


def test_process_issue_stamps_jsm_source_and_metadata(
    jsm_connector: JiraServiceManagementConnector,
    create_mock_jsm_issue: Callable[..., MagicMock],
) -> None:
    issue = create_mock_jsm_issue(
        key="IT-1",
        jsm_fields={
            "customfield_10010": {"requestType": {"id": "37", "name": "Get IT help"}},
            "customfield_10002": [{"id": "5", "name": "Acme Corp"}],
            "customfield_10003": [{"displayName": "Jane Customer"}],
            "customfield_10999": {
                "name": "Time to resolution",
                "ongoingCycle": {"breached": True},
            },
        },
    )

    document = jsm_connector._process_issue(issue, "IT")

    assert document is not None
    assert document.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
    assert document.id == "https://jira.example.com/browse/IT-1"
    assert document.metadata["customer_request_type"] == "Get IT help"
    assert document.metadata["organizations"] == ["Acme Corp"]
    assert document.metadata["request_participants"] == ["Jane Customer"]
    assert document.metadata["sla_status"] == ["Time to resolution: Breached"]
    # base Jira metadata still present
    assert document.metadata["key"] == "IT-1"
    assert document.metadata["project"] == "IT"
    assert document.metadata["issuetype"] == "Service Request"


def test_process_issue_filters_internal_comments(
    jsm_connector: JiraServiceManagementConnector,
    create_mock_jsm_issue: Callable[..., MagicMock],
) -> None:
    issue = create_mock_jsm_issue(
        comments=[
            create_mock_comment("customer-visible reply", jsd_public=True),
            create_mock_comment("internal agent note", jsd_public=False),
        ]
    )

    document = jsm_connector._process_issue(issue, "IT")

    assert document is not None
    text = document.sections[0].text or ""
    assert "customer-visible reply" in text
    assert "internal agent note" not in text


def test_process_issue_includes_internal_comments_when_enabled(
    jira_base_url: str,
    project_key: str,
    mock_jira_client: MagicMock,
    create_mock_jsm_issue: Callable[..., MagicMock],
) -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url=jira_base_url,
        project_key=project_key,
        include_internal_comments=True,
    )
    connector._jira_client = mock_jira_client

    issue = create_mock_jsm_issue(
        comments=[
            create_mock_comment("customer-visible reply", jsd_public=True),
            create_mock_comment("internal agent note", jsd_public=False),
        ]
    )

    document = connector._process_issue(issue, "IT")

    assert document is not None
    text = document.sections[0].text or ""
    assert "customer-visible reply" in text
    assert "[Internal Note] internal agent note" in text


def test_load_from_checkpoint_happy_path(
    jsm_connector: JiraServiceManagementConnector,
    create_mock_jsm_issue: Callable[..., MagicMock],
) -> None:
    mock_issue1 = create_mock_jsm_issue(key="IT-1", summary="Issue 1")
    mock_issue2 = create_mock_jsm_issue(key="IT-2", summary="Issue 2")
    mock_issue3 = create_mock_jsm_issue(key="IT-3", summary="Issue 3")

    jira_client = cast(JIRA, jsm_connector._jira_client)
    search_issues_mock = cast(MagicMock, jira_client.search_issues)
    search_issues_mock.side_effect = [
        [mock_issue1, mock_issue2],
        [mock_issue3],
        [],
    ]

    outputs = load_everything_from_checkpoint_connector(jsm_connector, 0, time.time())

    assert len(outputs) == 2
    documents = [
        item
        for output in outputs
        for item in output.items
        if isinstance(item, Document)
    ]
    assert [doc.id for doc in documents] == [
        "https://jira.example.com/browse/IT-1",
        "https://jira.example.com/browse/IT-2",
        "https://jira.example.com/browse/IT-3",
    ]
    assert all(
        doc.source == DocumentSource.JIRA_SERVICE_MANAGEMENT for doc in documents
    )
    assert outputs[0].next_checkpoint == JiraConnectorCheckpoint(
        offset=2, has_more=True, seen_hierarchy_node_ids=["IT"]
    )
    assert outputs[1].next_checkpoint.has_more is False


def test_label_skipped_issue_not_indexed_or_in_slim_docs(
    jsm_connector: JiraServiceManagementConnector,
    create_mock_jsm_issue: Callable[..., MagicMock],
) -> None:
    skipped = create_mock_jsm_issue(key="IT-1", labels=["secret"])
    kept = create_mock_jsm_issue(key="IT-2")

    jira_client = cast(JIRA, jsm_connector._jira_client)
    search_issues_mock = cast(MagicMock, jira_client.search_issues)
    search_issues_mock.side_effect = [[skipped, kept], []]

    outputs = load_everything_from_checkpoint_connector(jsm_connector, 0, time.time())
    documents = [
        item
        for output in outputs
        for item in output.items
        if isinstance(item, Document)
    ]
    assert [doc.id for doc in documents] == ["https://jira.example.com/browse/IT-2"]

    search_issues_mock.reset_mock()
    search_issues_mock.side_effect = [[skipped, kept]]
    slim_docs = [
        item
        for batch in jsm_connector.retrieve_all_slim_docs(0, time.time())
        for item in batch
        if isinstance(item, SlimDocument)
    ]
    assert [doc.id for doc in slim_docs] == ["https://jira.example.com/browse/IT-2"]


def test_attachments_emitted_as_documents(
    jsm_connector: JiraServiceManagementConnector,
    create_mock_jsm_issue: Callable[..., MagicMock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attachments = [
        create_mock_attachment(attachment_id="100", filename="report.pdf"),
        create_mock_attachment(
            attachment_id="101", filename="notes.txt", mime_type="text/plain"
        ),
    ]
    issue = create_mock_jsm_issue(key="IT-1", attachments=attachments)

    jira_client = cast(JIRA, jsm_connector._jira_client)
    cast(MagicMock, jira_client.search_issues).return_value = [issue]
    session = cast(MagicMock, jira_client._session)
    session.get.return_value.content = b"file contents here"
    session.get.return_value.raise_for_status = MagicMock()
    monkeypatch.setattr(
        "onyx.connectors.jira_service_management.connector.extract_file_text",
        MagicMock(return_value="file contents here"),
    )

    items = _collect_all_items(jsm_connector)

    hierarchy_nodes = [i for i in items if isinstance(i, HierarchyNode)]
    documents = [i for i in items if isinstance(i, Document)]
    failures = [i for i in items if isinstance(i, ConnectorFailure)]

    assert not failures

    # project node + issue-as-node (has admissible attachments)
    node_ids = {n.raw_node_id for n in hierarchy_nodes}
    assert "IT" in node_ids
    assert "https://jira.example.com/browse/IT-1" in node_ids

    doc_ids = {d.id for d in documents}
    assert doc_ids == {
        "https://jira.example.com/browse/IT-1",
        "https://jira.example.com/rest/api/3/attachment/content/100",
        "https://jira.example.com/rest/api/3/attachment/content/101",
    }

    attachment_docs = {d.id: d for d in documents if "attachment" in d.id}
    report = attachment_docs[
        "https://jira.example.com/rest/api/3/attachment/content/100"
    ]
    assert report.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
    assert report.parent_hierarchy_raw_node_id == (
        "https://jira.example.com/browse/IT-1"
    )
    assert report.metadata["filename"] == "report.pdf"
    assert report.metadata["parent_issue"] == "IT-1"
    assert report.semantic_identifier == "report.pdf (IT-1)"
    assert "file contents here" in (report.sections[0].text or "")


def test_attachments_disabled_by_default(
    jira_base_url: str,
    project_key: str,
    mock_jira_client: MagicMock,
    create_mock_jsm_issue: Callable[..., MagicMock],
) -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url=jira_base_url, project_key=project_key
    )
    connector._jira_client = mock_jira_client

    issue = create_mock_jsm_issue(key="IT-1", attachments=[create_mock_attachment()])
    cast(MagicMock, mock_jira_client.search_issues).return_value = [issue]

    items = _collect_all_items(connector)
    documents = [i for i in items if isinstance(i, Document)]

    assert len(documents) == 1
    assert documents[0].id == "https://jira.example.com/browse/IT-1"
    mock_jira_client._session.get.assert_not_called()


def test_attachment_download_failure_skips_attachment(
    jsm_connector: JiraServiceManagementConnector,
    create_mock_jsm_issue: Callable[..., MagicMock],
) -> None:
    issue = create_mock_jsm_issue(key="IT-1", attachments=[create_mock_attachment()])

    jira_client = cast(JIRA, jsm_connector._jira_client)
    cast(MagicMock, jira_client.search_issues).return_value = [issue]
    session = cast(MagicMock, jira_client._session)
    session.get.side_effect = RuntimeError("boom")

    items = _collect_all_items(jsm_connector)
    documents = [i for i in items if isinstance(i, Document)]

    # The ticket is still indexed; the attachment is skipped.
    assert [d.id for d in documents] == ["https://jira.example.com/browse/IT-1"]


def test_attachment_processing_error_yields_connector_failure(
    jsm_connector: JiraServiceManagementConnector,
    create_mock_jsm_issue: Callable[..., MagicMock],
) -> None:
    issue = create_mock_jsm_issue(key="IT-1", attachments=[create_mock_attachment()])
    jira_client = cast(JIRA, jsm_connector._jira_client)
    cast(MagicMock, jira_client.search_issues).return_value = [issue]
    session = cast(MagicMock, jira_client._session)
    session.get.return_value.content = b"file bytes"
    session.get.return_value.raise_for_status = MagicMock()

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            "onyx.connectors.jira_service_management.connector.extract_file_text",
            MagicMock(side_effect=RuntimeError("cannot parse")),
        )
        items = _collect_all_items(jsm_connector)

    documents = [i for i in items if isinstance(i, Document)]
    failures = [i for i in items if isinstance(i, ConnectorFailure)]

    assert [d.id for d in documents] == ["https://jira.example.com/browse/IT-1"]
    assert len(failures) == 1
    assert failures[0].failed_document is not None
    assert failures[0].failed_document.document_id == (
        "https://jira.example.com/rest/api/3/attachment/content/10001"
    )


def test_slim_docs_include_attachments_and_issue_node(
    jsm_connector: JiraServiceManagementConnector,
    create_mock_jsm_issue: Callable[..., MagicMock],
) -> None:
    attachments = [
        create_mock_attachment(attachment_id="100", filename="report.pdf"),
        # inadmissible attachment must not appear in the slim pass either
        create_mock_attachment(
            attachment_id="101",
            filename="virus.exe",
            mime_type="application/octet-stream",
        ),
    ]
    issue = create_mock_jsm_issue(key="IT-1", attachments=attachments)

    jira_client = cast(JIRA, jsm_connector._jira_client)
    cast(MagicMock, jira_client.search_issues).return_value = [issue]

    batches = list(jsm_connector.retrieve_all_slim_docs(0, time.time()))
    items = [item for batch in batches for item in batch]

    slim_docs = [i for i in items if isinstance(i, SlimDocument)]
    nodes = [i for i in items if isinstance(i, HierarchyNode)]

    assert [d.id for d in slim_docs] == [
        "https://jira.example.com/browse/IT-1",
        "https://jira.example.com/rest/api/3/attachment/content/100",
    ]
    issue_node = next(n for n in nodes if n.raw_node_id.endswith("/browse/IT-1"))
    assert issue_node.raw_parent_id == "IT"


def test_slim_attachment_perms_inherit_project(
    jsm_connector: JiraServiceManagementConnector,
    create_mock_jsm_issue: Callable[..., MagicMock],
) -> None:
    issue = create_mock_jsm_issue(key="IT-1", attachments=[create_mock_attachment()])
    jira_client = cast(JIRA, jsm_connector._jira_client)
    cast(MagicMock, jira_client.search_issues).return_value = [issue]

    expected_access = ExternalAccess(
        external_user_emails={"agent@example.com"},
        external_user_group_ids=set(),
        is_public=False,
    )
    jsm_connector._project_permissions_cache["IT:unprefixed"] = expected_access

    batches = list(jsm_connector.retrieve_all_slim_docs_perm_sync(0, time.time()))
    slim_docs = [i for batch in batches for i in batch if isinstance(i, SlimDocument)]
    assert len(slim_docs) == 2
    assert all(d.external_access == expected_access for d in slim_docs)


def test_attachment_doc_permissions_follow_ticket(
    jsm_connector: JiraServiceManagementConnector,
    create_mock_jsm_issue: Callable[..., MagicMock],
) -> None:
    issue = create_mock_jsm_issue(key="IT-1", attachments=[create_mock_attachment()])
    jira_client = cast(JIRA, jsm_connector._jira_client)
    cast(MagicMock, jira_client.search_issues).return_value = [issue]
    session = cast(MagicMock, jira_client._session)
    session.get.return_value.content = b"file bytes"
    session.get.return_value.raise_for_status = MagicMock()

    expected_access = ExternalAccess(
        external_user_emails={"agent@example.com"},
        external_user_group_ids=set(),
        is_public=False,
    )
    jsm_connector._project_permissions_cache["IT:prefixed"] = expected_access

    documents = [
        d
        for d in _collect_all_items(jsm_connector, perm_sync=True)
        if isinstance(d, Document)
    ]
    assert len(documents) == 2
    attachment_doc = next(d for d in documents if "attachment" in d.id)
    assert attachment_doc.external_access == expected_access


def test_image_attachment_gated_by_allow_images(
    jsm_connector: JiraServiceManagementConnector,
    create_mock_jsm_issue: Callable[..., MagicMock],
) -> None:
    image_attachment = create_mock_attachment(
        attachment_id="img1", filename="shot.png", mime_type="image/png"
    )
    issue = create_mock_jsm_issue(key="IT-1", attachments=[image_attachment])
    jira_client = cast(JIRA, jsm_connector._jira_client)
    cast(MagicMock, jira_client.search_issues).return_value = [issue]

    slim_ids = [
        d.id
        for batch in jsm_connector.retrieve_all_slim_docs(0, time.time())
        for d in batch
        if isinstance(d, SlimDocument)
    ]
    # image excluded while allow_images is off (slim pass agrees)
    assert all("attachment" not in i for i in slim_ids)

    jsm_connector.set_allow_images(True)
    slim_ids = [
        d.id
        for batch in jsm_connector.retrieve_all_slim_docs(0, time.time())
        for d in batch
        if isinstance(d, SlimDocument)
    ]
    assert "https://jira.example.com/rest/api/3/attachment/content/img1" in slim_ids


def test_validate_connector_settings_requires_project(
    jira_base_url: str, mock_jira_client: MagicMock
) -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url=jira_base_url, project_key="IT"
    )
    connector._jira_client = mock_jira_client
    connector.jira_project = None

    with pytest.raises(ConnectorValidationError, match="project key"):
        connector.validate_connector_settings()


def test_validate_connector_settings_rejects_non_service_desk_project(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    jira_client = cast(JIRA, jsm_connector._jira_client)
    project_mock = cast(MagicMock, jira_client.project)
    project = MagicMock()
    project.raw = {"projectTypeKey": "software"}
    project_mock.return_value = project

    with pytest.raises(ConnectorValidationError, match="service desk"):
        jsm_connector.validate_connector_settings()


def test_validate_connector_settings_accepts_service_desk_project(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    jira_client = cast(JIRA, jsm_connector._jira_client)
    project_mock = cast(MagicMock, jira_client.project)
    project = MagicMock()
    project.raw = {"projectTypeKey": "service_desk"}
    project_mock.return_value = project
    cast(MagicMock, jira_client.search_issues).return_value = []

    jsm_connector.validate_connector_settings()

    project_mock.assert_called_once_with("IT")
    # the validation JQL is project-scoped
    search_kwargs = cast(MagicMock, jira_client.search_issues).call_args.kwargs
    assert 'project = "IT"' in search_kwargs["jql_str"]


def test_validate_connector_settings_project_error(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    jira_client = cast(JIRA, jsm_connector._jira_client)
    cast(MagicMock, jira_client.project).side_effect = JIRAError(status_code=401)

    with pytest.raises(CredentialExpiredError):
        jsm_connector.validate_connector_settings()
