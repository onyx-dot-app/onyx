import inspect
import typing
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from jira.client import ResultList
from jira.exceptions import JIRAError
from jira.resources import Issue, PropertyHolder

from onyx.configs.constants import DocumentSource
from onyx.connectors.credential_families import to_source_credential_json
from onyx.connectors.credential_family_base import (
    CREDENTIAL_FAMILY_KEY,
    CredentialFamily,
)
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    InsufficientPermissionsError,
)
from onyx.connectors.field_policy import ScopeDirection
from onyx.connectors.interfaces import (
    CheckpointedConnector,
    CheckpointedConnectorWithPermSync,
    SlimConnector,
    SlimConnectorWithPermSync,
)
from onyx.connectors.jira_service_management.config import (
    JiraServiceManagementConnectorConfig,
    jira_service_management_planning_rule,
)
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
    JiraServiceManagementConnectorCheckpoint,
    process_jira_issue,
)
from onyx.connectors.jira_service_management.utils import (
    JIRA_CLOUD_API_VERSION,
    JIRA_CONNECT_TIMEOUT_SECONDS,
    JIRA_READ_TIMEOUT_SECONDS,
    JIRA_SERVER_API_VERSION,
    build_jira_client,
    build_jira_url,
    build_jsm_document_id,
    extract_text_from_adf,
    get_comment_strs,
)
from onyx.connectors.models import (
    ConnectorFailure,
    ConnectorMissingCredentialError,
    Document,
    SlimDocument,
)
from onyx.connectors.planning_rule_registry import PLANNING_RULES
from onyx.connectors.registry import CONNECTOR_CLASS_MAP
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface


def _make_property_holder(data: Any) -> Any:
    if isinstance(data, dict):
        holder = PropertyHolder()
        for k, v in data.items():
            setattr(holder, k, _make_property_holder(v))
        return holder
    if isinstance(data, list):
        return [_make_property_holder(item) for item in data]
    return data


def _make_mock_issue(
    key: str = "JSM-101",
    issue_id: str = "10100",
    summary: str = "VPN access request",
    description: object = "User needs corporate VPN access.",
    updated: str = "2026-11-20T12:00:00.000+0000",
    created: str = "2026-11-19T09:00:00.000+0000",
    project_key: str = "JSM",
    status_name: str = "Waiting for support",
    labels: list[str] | None = None,
    comments: list[tuple[str, object]] | None = None,
) -> SimpleNamespace:
    comment_objs = []
    for email, body in comments or []:
        comment_objs.append(
            SimpleNamespace(
                author=SimpleNamespace(emailAddress=email),
                body=body,
            )
        )
    return SimpleNamespace(
        id=issue_id,
        key=key,
        fields=SimpleNamespace(
            summary=summary,
            description=description,
            updated=updated,
            created=created,
            project=SimpleNamespace(key=project_key),
            status=SimpleNamespace(name=status_name),
            issuetype=SimpleNamespace(name="Service Request"),
            priority=SimpleNamespace(name="High"),
            creator=SimpleNamespace(
                displayName="Alice Requester",
                emailAddress="alice@example.com",
            ),
            labels=labels or [],
            comment=SimpleNamespace(comments=comment_objs),
        ),
    )


class _RecordingHeartbeat(IndexingHeartbeatInterface):
    def __init__(self, stop_after: int | None = None) -> None:
        self.stop_after = stop_after
        self.progress_calls: list[tuple[str, int]] = []

    def should_stop(self) -> bool:
        return (
            self.stop_after is not None and len(self.progress_calls) >= self.stop_after
        )

    def progress(self, tag: str, amount: int) -> None:
        self.progress_calls.append((tag, amount))


def test_registry_and_planning_rule_registration() -> None:
    mapping = CONNECTOR_CLASS_MAP[DocumentSource.JIRA_SERVICE_MANAGEMENT]
    assert mapping.module_path == "onyx.connectors.jira_service_management.connector"
    assert mapping.class_name == "JiraServiceManagementConnector"
    assert mapping.config_class is JiraServiceManagementConnectorConfig
    assert DocumentSource.JIRA_SERVICE_MANAGEMENT in PLANNING_RULES

    # Does not claim permission sync without ACL extraction.
    assert issubclass(JiraServiceManagementConnector, CheckpointedConnector)
    assert issubclass(JiraServiceManagementConnector, SlimConnector)
    assert not issubclass(
        JiraServiceManagementConnector, CheckpointedConnectorWithPermSync
    )
    assert not issubclass(JiraServiceManagementConnector, SlimConnectorWithPermSync)

    # Mirror test_connector_config_models.py exact signature/default parity.
    params = inspect.signature(JiraServiceManagementConnector.__init__).parameters
    named_params = {
        name: p
        for name, p in params.items()
        if name != "self" and p.kind not in (p.VAR_KEYWORD, p.VAR_POSITIONAL)
    }
    fields = JiraServiceManagementConnectorConfig.model_fields
    type_hints = typing.get_type_hints(JiraServiceManagementConnector.__init__)
    assert fields.keys() == named_params.keys()
    for name, param in named_params.items():
        field = fields[name]
        assert field.annotation == type_hints[name], name
        if param.default is param.empty:
            assert field.is_required(), name
        else:
            assert not field.is_required(), name
            assert field.get_default(call_default_factory=True) == param.default, name


def test_config_rejects_order_by_and_planning_rule_ignores_project_with_jql() -> None:
    with pytest.raises(ValueError, match="ORDER BY"):
        JiraServiceManagementConnectorConfig(
            jira_base_url="https://acme.atlassian.net",
            jql_query="project = JSM ORDER BY created DESC",
        )

    old = JiraServiceManagementConnectorConfig(
        jira_base_url="https://acme.atlassian.net",
        project_key="JSM",
        jql_query="project = JSM",
    )
    new = JiraServiceManagementConnectorConfig(
        jira_base_url="https://acme.atlassian.net",
        project_key="IT",
        jql_query="project = JSM",
    )
    override = jira_service_management_planning_rule(old, new)
    assert override is not None
    assert override.scope_directions == {"project_key": ScopeDirection.NONE}

    # Whitespace-only JQL behaves like unset JQL in both connector and planning rule.
    blank_old = JiraServiceManagementConnectorConfig(
        jira_base_url="https://acme.atlassian.net",
        project_key="JSM",
        jql_query="   ",
    )
    blank_new = JiraServiceManagementConnectorConfig(
        jira_base_url="https://acme.atlassian.net",
        project_key="IT",
        jql_query="   ",
    )
    assert jira_service_management_planning_rule(blank_old, blank_new) is None


def test_build_jira_client_cloud_token_only_scoped_and_timeout() -> None:
    with pytest.raises(ConnectorMissingCredentialError):
        build_jira_client({}, "https://acme.atlassian.net")

    with patch("onyx.connectors.jira_service_management.utils.JIRA") as mock_jira:
        build_jira_client(
            {"jira_user_email": "ops@acme.com", "jira_api_token": "tok"},
            "https://acme.atlassian.net/",
            scoped_token=False,
        )
        mock_jira.assert_called_once_with(
            server="https://acme.atlassian.net",
            options={"rest_api_version": JIRA_CLOUD_API_VERSION},
            basic_auth=("ops@acme.com", "tok"),
            timeout=(JIRA_CONNECT_TIMEOUT_SECONDS, JIRA_READ_TIMEOUT_SECONDS),
        )

    # Token-only Data Center / Server PAT credential.
    with patch("onyx.connectors.jira_service_management.utils.JIRA") as mock_jira:
        build_jira_client(
            {"jira_api_token": "pat-secret"},
            "https://jira.internal.corp/",
            scoped_token=False,
        )
        mock_jira.assert_called_once_with(
            server="https://jira.internal.corp",
            options={"rest_api_version": JIRA_SERVER_API_VERSION},
            token_auth="pat-secret",
            timeout=(JIRA_CONNECT_TIMEOUT_SECONDS, JIRA_READ_TIMEOUT_SECONDS),
        )

    # Scoped Cloud token routes through Atlassian gateway URL.
    with (
        patch(
            "onyx.connectors.jira_service_management.utils.scoped_url",
            return_value="https://api.atlassian.com/ex/jira/cloud-123",
        ) as mock_scoped,
        patch("onyx.connectors.jira_service_management.utils.JIRA") as mock_jira,
    ):
        build_jira_client(
            {"jira_user_email": "ops@acme.com", "jira_api_token": "scoped-tok"},
            "https://acme.atlassian.net/",
            scoped_token=True,
        )
        mock_scoped.assert_called_once_with("https://acme.atlassian.net", "jira")
        mock_jira.assert_called_once_with(
            server="https://api.atlassian.com/ex/jira/cloud-123",
            options={"rest_api_version": JIRA_CLOUD_API_VERSION},
            basic_auth=("ops@acme.com", "scoped-tok"),
            timeout=(JIRA_CONNECT_TIMEOUT_SECONDS, JIRA_READ_TIMEOUT_SECONDS),
        )


def test_extract_text_from_adf_dict_and_property_holder() -> None:
    adf_dict = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "Ticket "},
                    {"type": "text", "text": "JSM-"},
                    {"type": "text", "text": "101", "marks": [{"type": "strong"}]},
                ],
            },
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "Line 1"},
                    {"type": "hardBreak"},
                    {"type": "text", "text": "Line 2"},
                ],
            },
        ],
    }
    assert extract_text_from_adf(adf_dict) == "Ticket JSM-101\nLine 1\nLine 2"

    # Hydrated Jira SDK PropertyHolder objects must extract identical text.
    adf_holder = _make_property_holder(adf_dict)
    assert isinstance(adf_holder, PropertyHolder)
    assert extract_text_from_adf(adf_holder) == "Ticket JSM-101\nLine 1\nLine 2"

    comment_holder = _make_property_holder(
        {
            "type": "doc",
            "content": [{"type": "text", "text": "Resolved VPN profile"}],
        }
    )
    issue = _make_mock_issue(
        description=adf_holder,
        comments=[
            ("bot@example.com", "Automated triage"),
            ("agent@example.com", comment_holder),
        ],
    )
    filtered = get_comment_strs(issue, comment_email_blacklist=["bot@example.com"])
    assert filtered == ["Resolved VPN profile"]

    doc = process_jira_issue(
        "https://acme.atlassian.net",
        issue,  # type: ignore[arg-type]
    )
    assert doc is not None
    assert doc.sections[0].text is not None
    assert "Ticket JSM-101" in doc.sections[0].text
    assert "Comment: Resolved VPN profile" in doc.sections[0].text


def test_process_jira_issue_and_label_skip() -> None:
    issue = _make_mock_issue(labels=["internal-secret"])
    assert (
        process_jira_issue(
            "https://acme.atlassian.net",
            issue,  # type: ignore[arg-type]
            labels_to_skip=["internal-secret"],
        )
        is None
    )

    doc = process_jira_issue(
        "https://acme.atlassian.net",
        _make_mock_issue(comments=[("agent@example.com", "Ticket assigned")]),  # type: ignore[arg-type]
        labels_to_skip=[],
    )
    assert doc is not None
    assert doc.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
    assert doc.id == build_jsm_document_id("https://acme.atlassian.net", "JSM-101")
    assert doc.sections[0].link == "https://acme.atlassian.net/browse/JSM-101"
    assert doc.sections[0].text is not None
    assert "User needs corporate VPN access." in doc.sections[0].text
    assert "Comment: Ticket assigned" in doc.sections[0].text
    assert doc.metadata["project"] == "JSM"
    assert doc.metadata["status"] == "Waiting for support"


def test_jql_uses_epoch_ms_and_deterministic_ordering() -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://acme.atlassian.net/",
        project_key="JSM",
    )
    jql = connector._build_jql(start=1700000000, end=1700003600, after_issue_id=500)
    assert 'project = "JSM"' in jql
    assert "updated >= 1700000000000" in jql
    assert "updated <= 1700003600000" in jql
    assert "id > 500" in jql
    assert jql.endswith("ORDER BY id ASC")


def test_cloud_checkpoint_and_slim_pagination_use_continuation_tokens() -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://acme.atlassian.net/",
        project_key="JSM",
        batch_size=500,
        labels_to_skip=["skip-me"],
    )
    mock_client = MagicMock()
    mock_client.deploymentType = "Cloud"
    # Even when page size (1) < batch_size (500), nextPageToken drives has_more.
    page1: ResultList[Any] = ResultList(
        [
            _make_mock_issue(key="JSM-1", issue_id="101", summary="First request"),
            _make_mock_issue(
                key="JSM-2",
                issue_id="102",
                summary="Skipped request",
                labels=["skip-me"],
            ),
        ],
        _nextPageToken="tok-page-2",
        _isLast=False,
    )
    page2: ResultList[Any] = ResultList(
        [_make_mock_issue(key="JSM-3", issue_id="103", summary="Third request")],
        _nextPageToken=None,
        _isLast=True,
    )
    mock_client.enhanced_search_issues.side_effect = [page1, page2]
    connector._jira_client = mock_client
    connector._is_cloud = True

    cp0 = JiraServiceManagementConnectorCheckpoint(has_more=True)
    gen1 = connector.load_from_checkpoint(1700000000, 1700003600, cp0)
    docs1: list[Document] = []
    try:
        while True:
            item = next(gen1)
            assert isinstance(item, Document)
            docs1.append(item)
    except StopIteration as stop:
        cp1 = stop.value

    assert [d.id for d in docs1] == [
        build_jsm_document_id("https://acme.atlassian.net", "JSM-1")
    ]
    assert cp1.has_more is True
    assert cp1.next_page_token == "tok-page-2"
    assert cp1.pinned_end == 1700003600

    # Even if caller passes a later end timestamp on resume, pinned_end keeps
    # the query window fixed across checkpoint resumptions.
    gen2 = connector.load_from_checkpoint(1700000000, 1700009999, cp1)
    docs2: list[Document] = []
    try:
        while True:
            item = next(gen2)
            assert isinstance(item, Document)
            docs2.append(item)
    except StopIteration as stop:
        cp2 = stop.value

    assert [d.id for d in docs2] == [
        build_jsm_document_id("https://acme.atlassian.net", "JSM-3")
    ]
    assert cp2.has_more is False
    assert cp2.next_page_token is None

    second_call = mock_client.enhanced_search_issues.call_args_list[1].kwargs
    assert second_call["nextPageToken"] == "tok-page-2"
    assert "updated <= 1700003600000" in second_call["jql_str"]
    mock_client.search_issues.assert_not_called()

    # Slim listing uses enhanced_search_issues + callback heartbeat.
    mock_client.enhanced_search_issues.reset_mock()
    mock_client.enhanced_search_issues.side_effect = [page1, page2]
    heartbeat = _RecordingHeartbeat()
    slim_batches = list(
        connector.retrieve_all_slim_docs(
            start=1700000000, end=1700003600, callback=heartbeat
        )
    )
    assert [
        [d.id for d in batch if isinstance(d, SlimDocument)] for batch in slim_batches
    ] == [
        [build_jsm_document_id("https://acme.atlassian.net", "JSM-1")],
        [build_jsm_document_id("https://acme.atlassian.net", "JSM-3")],
    ]
    assert len(heartbeat.progress_calls) == 2


def test_server_keyset_pagination_and_metadata_has_more() -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://jira.internal.corp",
        project_key="JSM",
        batch_size=500,
    )
    mock_client = MagicMock()
    mock_client.deploymentType = "Server"
    # Capped page of 1 item with total=2 still sets has_more=True.
    page1: ResultList[Any] = ResultList(
        [_make_mock_issue(key="JSM-10", issue_id="1000")],
        _startAt=0,
        _maxResults=1,
        _total=2,
    )
    page2: ResultList[Any] = ResultList(
        [_make_mock_issue(key="JSM-11", issue_id="1001")],
        _startAt=0,
        _maxResults=1,
        _total=1,
    )
    mock_client.search_issues.side_effect = [page1, page2]
    connector._jira_client = mock_client
    connector._is_cloud = False

    cp0 = JiraServiceManagementConnectorCheckpoint(has_more=True)
    gen1 = connector.load_from_checkpoint(1700000000, 1700003600, cp0)
    try:
        while True:
            next(gen1)
    except StopIteration as stop:
        cp1 = stop.value

    assert cp1.has_more is True
    assert cp1.last_issue_id == 1000

    gen2 = connector.load_from_checkpoint(1700000000, 1700003600, cp1)
    try:
        while True:
            next(gen2)
    except StopIteration as stop:
        cp2 = stop.value

    assert cp2.has_more is False
    assert cp2.last_issue_id == 1001
    second_call = mock_client.search_issues.call_args_list[1].kwargs
    assert second_call["startAt"] == 0
    assert "id > 1000" in second_call["jql_str"]


def test_jira_error_translation() -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://acme.atlassian.net",
        project_key="JSM",
    )
    mock_client = MagicMock()
    mock_client.deploymentType = "Cloud"
    connector._jira_client = mock_client
    connector._is_cloud = True

    mock_client.enhanced_search_issues.side_effect = JIRAError(
        status_code=401, text="Unauthorized"
    )
    with pytest.raises(CredentialExpiredError):
        list(
            connector.load_from_checkpoint(
                1700000000, 1700003600, connector.build_dummy_checkpoint()
            )
        )

    mock_client.enhanced_search_issues.side_effect = JIRAError(
        status_code=403, text="Forbidden"
    )
    with pytest.raises(InsufficientPermissionsError):
        list(
            connector.load_from_checkpoint(
                1700000000, 1700003600, connector.build_dummy_checkpoint()
            )
        )

    mock_client.project.side_effect = JIRAError(status_code=404, text="Not found")
    with pytest.raises(ConnectorValidationError):
        connector.validate_connector_settings()


def test_real_hydrated_jira_issue_adf_and_token_only_family_credential() -> None:
    raw_issue = {
        "id": "20455",
        "key": "JSM-204",
        "fields": {
            "summary": "Laptop replacement",
            "description": {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [
                            {"type": "text", "text": "Need new workstation"},
                            {"type": "text", "text": "with Linux image"},
                        ],
                    }
                ],
            },
            "updated": "2026-11-20T15:00:00.000+0000",
            "project": {"key": "JSM"},
            "status": {"name": "Open"},
            "issuetype": {"name": "Hardware"},
            "priority": {"name": "Medium"},
            "creator": {
                "displayName": "Bob Agent",
                "emailAddress": "bob@example.com",
            },
            "labels": ["hardware"],
            "comment": {
                "comments": [
                    {
                        "author": {"emailAddress": "agent@example.com"},
                        "body": {
                            "type": "doc",
                            "version": 1,
                            "content": [
                                {
                                    "type": "paragraph",
                                    "content": [
                                        {"type": "text", "text": "Shipped tracking #99"}
                                    ],
                                }
                            ],
                        },
                    }
                ]
            },
        },
    }
    hydrated_issue = Issue(options={}, session=MagicMock(), raw=raw_issue)
    # Confirm jira SDK hydrated fields.description into a PropertyHolder.
    assert isinstance(hydrated_issue.fields.description, PropertyHolder)
    assert (
        extract_text_from_adf(hydrated_issue.fields.description)
        == "Need new workstationwith Linux image"
    )

    doc = process_jira_issue("https://acme.atlassian.net", hydrated_issue)
    assert doc is not None
    assert doc.sections[0].text is not None
    assert "Need new workstationwith Linux image" in doc.sections[0].text
    assert "Comment: Shipped tracking #99" in doc.sections[0].text
    assert doc.metadata["labels"] == ["hardware"]

    # End-to-end token-only Atlassian family credential -> load_credentials -> token_auth.
    stored_family_cred = {
        CREDENTIAL_FAMILY_KEY: CredentialFamily.ATLASSIAN.value,
        "token": "dc-pat-token",
    }
    source_cred = to_source_credential_json(
        DocumentSource.JIRA_SERVICE_MANAGEMENT, stored_family_cred
    )
    assert source_cred == {"jira_api_token": "dc-pat-token"}

    connector = JiraServiceManagementConnector(
        jira_base_url="https://jira.internal.corp", project_key="JSM"
    )
    with patch("onyx.connectors.jira_service_management.utils.JIRA") as mock_jira:
        connector.load_credentials(source_cred)
        assert connector._is_cloud is False
        mock_jira.assert_called_once_with(
            server="https://jira.internal.corp",
            options={"rest_api_version": JIRA_SERVER_API_VERSION},
            token_auth="dc-pat-token",
            timeout=(JIRA_CONNECT_TIMEOUT_SECONDS, JIRA_READ_TIMEOUT_SECONDS),
        )


def test_slim_docs_honors_callback_should_stop() -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://acme.atlassian.net", project_key="JSM"
    )
    mock_client = MagicMock()
    mock_client.deploymentType = "Cloud"
    mock_client.enhanced_search_issues.side_effect = [
        ResultList(
            [_make_mock_issue(key="JSM-1", issue_id="1")],
            _nextPageToken="page-2",
            _isLast=False,
        ),
        ResultList(
            [_make_mock_issue(key="JSM-2", issue_id="2")],
            _nextPageToken=None,
            _isLast=True,
        ),
    ]
    connector._jira_client = mock_client
    connector._is_cloud = True

    heartbeat = _RecordingHeartbeat(stop_after=1)
    batches = list(connector.retrieve_all_slim_docs(callback=heartbeat))
    assert len(batches) == 1
    assert mock_client.enhanced_search_issues.call_count == 1


def test_cloud_guards_empty_page_continuation_and_per_issue_failure_isolation() -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://acme.atlassian.net", project_key="JSM"
    )
    mock_client = MagicMock()
    mock_client.deploymentType = "Cloud"
    connector._jira_client = mock_client
    connector._is_cloud = True

    # Cloud returning None must raise rather than silently succeeding empty.
    mock_client.enhanced_search_issues.return_value = None
    with pytest.raises(RuntimeError, match="returned no result"):
        list(
            connector.load_from_checkpoint(
                1700000000, 1700003600, connector.build_dummy_checkpoint()
            )
        )

    # Repeated nextPageToken must raise to prevent infinite loops.
    mock_client.enhanced_search_issues.return_value = ResultList(
        [_make_mock_issue(key="JSM-1", issue_id="1")],
        _nextPageToken="stuck-token",
        _isLast=False,
    )
    with pytest.raises(RuntimeError, match="did not advance"):
        list(
            connector.load_from_checkpoint(
                1700000000,
                1700003600,
                JiraServiceManagementConnectorCheckpoint(
                    next_page_token="stuck-token", has_more=True
                ),
            )
        )

    # Empty Cloud page with continuation token must keep scanning in slim mode.
    mock_client.enhanced_search_issues.side_effect = [
        ResultList([], _nextPageToken="tok-2", _isLast=False),
        ResultList(
            [_make_mock_issue(key="JSM-9", issue_id="9")],
            _nextPageToken=None,
            _isLast=True,
        ),
    ]
    slim_batches = list(connector.retrieve_all_slim_docs())
    assert [
        [d.id for d in batch if isinstance(d, SlimDocument)] for batch in slim_batches
    ] == [[build_jsm_document_id("https://acme.atlassian.net", "JSM-9")]]

    # Per-issue conversion error yields ConnectorFailure and continues the page.
    mock_client.enhanced_search_issues.side_effect = None
    mock_client.enhanced_search_issues.return_value = ResultList(
        [
            _make_mock_issue(key="JSM-BAD", issue_id="50", updated="not-a-date"),
            _make_mock_issue(key="JSM-OK", issue_id="51"),
        ],
        _nextPageToken=None,
        _isLast=True,
    )
    gen = connector.load_from_checkpoint(
        1700000000, 1700003600, connector.build_dummy_checkpoint()
    )
    results: list[Any] = []
    try:
        while True:
            results.append(next(gen))
    except StopIteration as stop:
        final_cp = stop.value

    assert isinstance(results[0], ConnectorFailure)
    assert results[0].failed_document is not None
    assert results[0].failed_document.document_id == build_jsm_document_id(
        "https://acme.atlassian.net", "JSM-BAD"
    )
    assert results[0].failed_document.document_link == build_jira_url(
        "https://acme.atlassian.net", "JSM-BAD"
    )
    assert isinstance(results[1], Document)
    assert results[1].id == build_jsm_document_id(
        "https://acme.atlassian.net", "JSM-OK"
    )
    assert final_cp.has_more is False


def test_paginated_comments_beyond_embedded_cap_and_multiproject_server_watermark() -> (
    None
):
    # Short, nonempty comment pages (< _COMMENT_PAGE_SIZE) must keep paginating
    # while cursor < total, and stop cleanly on an empty page or at total.
    issue = SimpleNamespace(
        id="300",
        key="JSM-300",
        raw={
            "id": "300",
            "key": "JSM-300",
            "fields": {
                "comment": {
                    "total": 5,
                    "comments": [
                        {"author": {"emailAddress": "a@acme.com"}, "body": "First"},
                        {"author": {"emailAddress": "bot@acme.com"}, "body": "Bot"},
                    ],
                }
            },
        },
    )
    mock_client = MagicMock()
    mock_client.comments.side_effect = [
        [
            SimpleNamespace(
                author=SimpleNamespace(emailAddress="c@acme.com"),
                body="Third short page",
            )
        ],
        [
            SimpleNamespace(
                author=SimpleNamespace(emailAddress="d@acme.com"),
                body="Fourth short page",
            ),
            SimpleNamespace(
                author=SimpleNamespace(emailAddress="e@acme.com"),
                body="Fifth final comment",
            ),
        ],
    ]
    comments = get_comment_strs(
        issue,
        comment_email_blacklist=["bot@acme.com"],
        jira_client=mock_client,
    )
    assert comments == [
        "First",
        "Third short page",
        "Fourth short page",
        "Fifth final comment",
    ]
    assert mock_client.comments.call_count == 2
    assert mock_client.comments.call_args_list[0].kwargs == {
        "start_at": 2,
        "max_results": 50,
    }
    assert mock_client.comments.call_args_list[1].kwargs == {
        "start_at": 3,
        "max_results": 50,
    }

    # Multi-project Server/DC JQL uses an `updated` watermark cursor with
    # `startAt=0` and same-minute `id not in (...)` exclusion so issues leaving
    # the pinned window never shift/skip subsequent issues.
    multi_conn = JiraServiceManagementConnector(
        jira_base_url="https://jira.internal.corp",
        jql_query="project in (JSM, ITSM)",
        batch_size=1,
    )
    dc_client = MagicMock()
    dc_client.deploymentType = "Server"
    # Matches at t0: [10, 20, 30]. After page 1 returns issue 10, issue 10 is
    # updated past pinned_end and leaves the window ([20, 30] remain).
    dc_client.search_issues.side_effect = [
        ResultList(
            [
                _make_mock_issue(
                    key="JSM-1",
                    issue_id="10",
                    updated="2026-11-20T12:00:10.000+0000",
                )
            ],
            _startAt=0,
            _maxResults=1,
            _total=3,
        ),
        ResultList(
            [
                _make_mock_issue(
                    key="ITSM-2",
                    issue_id="20",
                    updated="2026-11-20T12:00:20.000+0000",
                )
            ],
            _startAt=0,
            _maxResults=1,
            _total=2,
        ),
        ResultList(
            [
                _make_mock_issue(
                    key="ITSM-3",
                    issue_id="30",
                    updated="2026-11-20T12:02:00.000+0000",
                )
            ],
            _startAt=0,
            _maxResults=1,
            _total=1,
        ),
    ]
    multi_conn._jira_client = dc_client
    multi_conn._is_cloud = False

    cp = multi_conn.build_dummy_checkpoint()
    seen_doc_ids: list[str] = []
    checkpoints: list[JiraServiceManagementConnectorCheckpoint] = []
    while cp.has_more:
        gen = multi_conn.load_from_checkpoint(1700000000, 1799999999, cp)
        try:
            while True:
                item = next(gen)
                assert isinstance(item, Document)
                seen_doc_ids.append(item.id)
        except StopIteration as stop:
            cp = stop.value
            checkpoints.append(cp)

    assert seen_doc_ids == [
        build_jsm_document_id("https://jira.internal.corp", "JSM-1"),
        build_jsm_document_id("https://jira.internal.corp", "ITSM-2"),
        build_jsm_document_id("https://jira.internal.corp", "ITSM-3"),
    ]
    assert checkpoints[0].offset == 0
    assert checkpoints[0].cursor_seen_ids == [10]
    assert checkpoints[1].cursor_seen_ids == [10, 20]
    # Advancing to a new minute bucket resets the excluded ID list.
    assert checkpoints[2].cursor_seen_ids == [30]
    assert checkpoints[2].has_more is False

    second_kwargs = dc_client.search_issues.call_args_list[1].kwargs
    assert second_kwargs["startAt"] == 0
    assert "id >" not in second_kwargs["jql_str"]
    assert "id not in (10)" in second_kwargs["jql_str"]
    assert second_kwargs["jql_str"].endswith("ORDER BY updated ASC, id ASC")

    third_kwargs = dc_client.search_issues.call_args_list[2].kwargs
    assert third_kwargs["startAt"] == 0
    assert "id not in (10, 20)" in third_kwargs["jql_str"]

    # Slim retrieval uses the same watermark cursor so shifted rows are not skipped.
    dc_client.search_issues.reset_mock()
    dc_client.search_issues.side_effect = [
        ResultList(
            [
                _make_mock_issue(
                    key="JSM-1",
                    issue_id="10",
                    updated="2026-11-20T12:00:10.000+0000",
                )
            ],
            _startAt=0,
            _maxResults=1,
            _total=3,
        ),
        ResultList(
            [
                _make_mock_issue(
                    key="ITSM-2",
                    issue_id="20",
                    updated="2026-11-20T12:00:20.000+0000",
                )
            ],
            _startAt=0,
            _maxResults=1,
            _total=2,
        ),
        ResultList(
            [
                _make_mock_issue(
                    key="ITSM-3",
                    issue_id="30",
                    updated="2026-11-20T12:02:00.000+0000",
                )
            ],
            _startAt=0,
            _maxResults=1,
            _total=1,
        ),
    ]
    slim_ids = [
        doc.id
        for batch in multi_conn.retrieve_all_slim_docs(start=1700000000, end=1799999999)
        for doc in batch
        if isinstance(doc, SlimDocument)
    ]
    assert slim_ids == seen_doc_ids
    slim_second = dc_client.search_issues.call_args_list[1].kwargs
    assert slim_second["startAt"] == 0
    assert "id not in (10)" in slim_second["jql_str"]
    assert "updated" in slim_second["fields"]
