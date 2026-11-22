"""Unit tests for the Jira Service Management connector.

Covers the two things the connector changes on top of the Jira connector:
documents are stamped with the JSM document source, and their metadata gains
the JSM portal fields (request type, portal status, SLA breach summary) when
the Service Desk API answers - with every enrichment failure swallowed so an
indexing run never breaks on JSM being unavailable.
"""

from typing import Any
from unittest.mock import MagicMock, call, patch

from onyx.configs.constants import DocumentSource
from onyx.connectors.jira.connector import JiraConnector
from onyx.connectors.jira.source_operations import _SERVICEDESK_BASE_URL
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
    _sla_breached_summary,
)
from onyx.connectors.models import Document


def _make_issue(key: str, project_key: str = "HELP") -> dict[str, Any]:
    """Build a minimal synthetic JSM issue payload for unit tests."""
    return {
        "key": key,
        "fields": {
            "project": {
                "key": project_key,
                "name": "Help Desk",
                "projectTypeKey": "service_desk",
            },
            "summary": f"Summary for {key}",
            "description": None,
            "comment": {"comments": []},
            "parent": None,
            "labels": [],
            "created": "2026-01-01T12:00:00.000+0000",
            "updated": "2026-01-02T12:00:00.000+0000",
        },
    }


def _documents(
    connector: JiraServiceManagementConnector, issue: dict[str, Any]
) -> list[Document]:
    """Run ``_issue_to_items`` with hierarchy stubs and return emitted Documents."""
    with (
        patch.object(
            JiraConnector, "_yield_project_hierarchy_node", return_value=iter([])
        ),
        patch.object(
            JiraConnector,
            "_yield_parent_hierarchy_node_if_epic",
            return_value=iter([]),
        ),
        patch.object(
            JiraConnector, "_yield_epic_hierarchy_node", return_value=iter([])
        ),
        patch.object(JiraConnector, "_is_epic", return_value=False),
        patch.object(
            JiraConnector, "_get_parent_hierarchy_raw_node_id", return_value=None
        ),
    ):
        return [
            item
            for item in connector._issue_to_items(
                issue, set(), include_permissions=False
            )
            if isinstance(item, Document)
        ]


def test_documents_carry_the_jsm_source(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    """Verify indexed JSM tickets carry DocumentSource.JIRA_SERVICE_MANAGEMENT."""
    docs = _documents(jsm_connector, _make_issue("HELP-1"))
    assert len(docs) == 1
    assert docs[0].source == DocumentSource.JIRA_SERVICE_MANAGEMENT


def test_portal_metadata_is_added_when_available(
    jsm_connector: JiraServiceManagementConnector, mock_source_operations: MagicMock
) -> None:
    """Verify Service Desk request type, portal status, and SLA metadata enrichment."""
    mock_source_operations.get_service_desk_request.return_value = {
        "requestType": {"name": "Report a system problem"},
        "currentStatus": {"status": "Waiting for support"},
    }
    mock_source_operations.get_service_desk_sla.return_value = {
        "values": [{"ongoingCycle": {"breached": True}}]
    }

    docs = _documents(jsm_connector, _make_issue("HELP-2"))

    assert docs[0].metadata["request_type"] == "Report a system problem"
    assert docs[0].metadata["portal_status"] == "Waiting for support"
    assert docs[0].metadata["sla_breached"] == "true"
    mock_source_operations.get_service_desk_request.assert_called_once_with(
        issue_key="HELP-2", fast=True
    )
    mock_source_operations.get_service_desk_sla.assert_called_once_with(
        issue_key="HELP-2", fast=True
    )


def test_enrichment_failure_still_indexes_the_ticket(
    jsm_connector: JiraServiceManagementConnector,
    mock_source_operations: MagicMock,  # noqa: ARG001
) -> None:
    """JSM not installed / no service desk access: gateway returns None and
    the ticket must index unchanged apart from the source stamp."""
    docs = _documents(jsm_connector, _make_issue("HELP-3"))

    assert len(docs) == 1
    assert docs[0].source == DocumentSource.JIRA_SERVICE_MANAGEMENT
    assert "request_type" not in docs[0].metadata
    assert "portal_status" not in docs[0].metadata
    assert "sla_breached" not in docs[0].metadata


def test_labels_to_skip_still_apply(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    """Verify inherited Jira labels_to_skip filtering still skips JSM tickets."""
    issue = _make_issue("HELP-4")
    issue["fields"]["labels"] = ["secret"]
    assert _documents(jsm_connector, issue) == []


def test_sla_breached_summary() -> None:
    """Verify _sla_breached_summary evaluates ongoing and completed SLA cycles."""
    assert (
        _sla_breached_summary({"values": [{"ongoingCycle": {"breached": False}}]})
        == "false"
    )
    assert (
        _sla_breached_summary(
            {
                "values": [
                    {"ongoingCycle": {"breached": False}},
                    {"completedCycles": [{"breached": True}]},
                ]
            }
        )
        == "true"
    )
    assert _sla_breached_summary({"values": []}) is None
    assert _sla_breached_summary({}) is None

    # Incomplete pagination without a breach must not record "false".
    assert (
        _sla_breached_summary(
            {
                "values": [{"ongoingCycle": {"breached": False}}],
                "isLastPage": False,
            }
        )
        is None
    )
    assert (
        _sla_breached_summary(
            {
                "values": [{"ongoingCycle": {"breached": False}}],
                "_links": {"next": "https://example.atlassian.net/sla?start=1"},
            }
        )
        is None
    )
    # A known breach remains "true" even if later pages are incomplete.
    assert (
        _sla_breached_summary(
            {
                "values": [{"completedCycles": [{"breached": True}]}],
                "isLastPage": False,
            }
        )
        == "true"
    )


def test_service_desk_url_is_not_under_the_versioned_jira_root() -> None:
    """Regression: the SDK's default base would resolve the Service Desk
    calls to ``{server}/rest/api/3/rest/servicedeskapi/...`` and 404."""
    url = _SERVICEDESK_BASE_URL.format(
        server="https://example.atlassian.net",
        rest_path="api",
        rest_api_version="3",
        path="request/IT-1",
    )
    assert url == "https://example.atlassian.net/rest/servicedeskapi/request/IT-1"
    assert "/rest/api/" not in url


def test_service_desk_ops_pass_the_servicedesk_base() -> None:
    """The gateway ops must call the SDK with the Service Desk base."""
    from onyx.connectors.jira.source_operations import JiraSourceOperations

    client = MagicMock()
    client._get_json.return_value = {"values": []}
    ops = JiraSourceOperations.__new__(JiraSourceOperations)
    ops._cached_client = client
    ops._cached_fast_client = client

    ops.get_service_desk_request(issue_key="IT-1")
    client._get_json.assert_called_with(
        "request/IT-1",
        params={"expand": "requestType"},
        base=_SERVICEDESK_BASE_URL,
    )

    ops.get_service_desk_sla(issue_key="IT-1")
    client._get_json.assert_called_with("request/IT-1/sla", base=_SERVICEDESK_BASE_URL)


def test_service_desk_ops_swallow_lookup_errors() -> None:
    """A raised _get_json error (JiraApiError / RequestException) must come
    back as None so enrichment never breaks an indexing run."""
    import requests

    from onyx.connectors.jira.source_operations import (
        JiraApiError,
        JiraSourceOperations,
    )

    for exc in (
        JiraApiError("boom", status_code=500),
        requests.RequestException("boom"),
    ):
        client = MagicMock()
        client._get_json.side_effect = exc
        ops = JiraSourceOperations.__new__(JiraSourceOperations)
        ops._cached_client = client
        ops._cached_fast_client = client

        assert ops.get_service_desk_request(issue_key="IT-1") is None
        assert ops.get_service_desk_sla(issue_key="IT-1") is None


def test_get_service_desk_sla_paginates_all_pages() -> None:
    """get_service_desk_sla must follow pages so a breach on a later page is seen."""
    from onyx.connectors.jira.source_operations import JiraSourceOperations

    client = MagicMock()
    client._get_json.side_effect = [
        {
            "start": 0,
            "isLastPage": False,
            "values": [{"ongoingCycle": {"breached": False}}],
        },
        {
            "start": 1,
            "isLastPage": True,
            "values": [{"completedCycles": [{"breached": True}]}],
        },
    ]
    ops = JiraSourceOperations.__new__(JiraSourceOperations)
    ops._cached_client = client
    ops._cached_fast_client = client

    sla = ops.get_service_desk_sla(issue_key="IT-1")
    assert sla == {
        "values": [
            {"ongoingCycle": {"breached": False}},
            {"completedCycles": [{"breached": True}]},
        ],
        "isLastPage": True,
    }
    assert _sla_breached_summary(sla) == "true"
    assert client._get_json.call_args_list == [
        call("request/IT-1/sla", base=_SERVICEDESK_BASE_URL),
        call("request/IT-1/sla", params={"start": 1}, base=_SERVICEDESK_BASE_URL),
    ]


def test_get_service_desk_sla_marks_partial_failure_incomplete() -> None:
    """If page 2 fails, unbreached partial results must not report 'false',
    while an already-seen breach still reports 'true'."""
    import requests

    from onyx.connectors.jira.source_operations import JiraSourceOperations

    # Unbreached page 1 + error on page 2 -> incomplete -> summary is None.
    client = MagicMock()
    client._get_json.side_effect = [
        {
            "start": 0,
            "isLastPage": False,
            "values": [{"ongoingCycle": {"breached": False}}],
        },
        requests.RequestException("boom"),
    ]
    ops = JiraSourceOperations.__new__(JiraSourceOperations)
    ops._cached_client = client
    ops._cached_fast_client = client

    partial_unbreached = ops.get_service_desk_sla(issue_key="IT-1")
    assert partial_unbreached == {
        "values": [{"ongoingCycle": {"breached": False}}],
        "isLastPage": False,
    }
    assert _sla_breached_summary(partial_unbreached) is None

    # Breached page 1 + error on page 2 -> still incomplete, summary is "true".
    client._get_json.side_effect = [
        {
            "start": 0,
            "isLastPage": False,
            "values": [{"ongoingCycle": {"breached": True}}],
        },
        requests.RequestException("boom"),
    ]
    partial_breached = ops.get_service_desk_sla(issue_key="IT-1")
    assert partial_breached == {
        "values": [{"ongoingCycle": {"breached": True}}],
        "isLastPage": False,
    }
    assert _sla_breached_summary(partial_breached) == "true"


def test_get_service_desk_sla_stops_on_stalled_pagination() -> None:
    """Zero-progress or rewound offsets must stop and mark result incomplete."""
    from onyx.connectors.jira.source_operations import JiraSourceOperations

    client = MagicMock()
    client._get_json.side_effect = [
        {
            "start": 0,
            "_links": {"next": "https://example.atlassian.net/sla?start=1"},
            "values": [{"ongoingCycle": {"breached": False}}],
        },
        {
            "start": 0,
            "_links": {"next": "https://example.atlassian.net/sla?start=1"},
            "values": [{"ongoingCycle": {"breached": False}}],
        },
    ]
    ops = JiraSourceOperations.__new__(JiraSourceOperations)
    ops._cached_client = client
    ops._cached_fast_client = client

    sla = ops.get_service_desk_sla(issue_key="IT-1")
    assert sla == {
        "values": [{"ongoingCycle": {"breached": False}}],
        "isLastPage": False,
    }
    assert _sla_breached_summary(sla) is None


def test_everything_scope_skips_non_service_desk_projects(
    jsm_connector: JiraServiceManagementConnector,
    mock_source_operations: MagicMock,
) -> None:
    """Default Everything scope: ordinary Jira issues must not index under
    the JSM source."""
    jsm_connector.jira_project = None  # Everything scope
    software_issue = _make_issue("ENG-1", project_key="ENG")
    software_issue["fields"]["project"]["projectTypeKey"] = "software"

    assert _documents(jsm_connector, software_issue) == []
    mock_source_operations.get_service_desk_request.assert_not_called()
    mock_source_operations.get_service_desk_sla.assert_not_called()


def test_project_scope_indexes_non_service_desk_without_enrichment(
    jsm_connector: JiraServiceManagementConnector,
    mock_source_operations: MagicMock,
) -> None:
    """Explicit Project/JQL scope is the user's choice: the issue still
    indexes, but no portal lookups are made for a known software project."""
    jsm_connector.jira_project = "ENG"
    software_issue = _make_issue("ENG-2", project_key="ENG")
    software_issue["fields"]["project"]["projectTypeKey"] = "software"

    docs = _documents(jsm_connector, software_issue)

    assert len(docs) == 1
    assert docs[0].source is DocumentSource.JIRA_SERVICE_MANAGEMENT
    assert "request_type" not in docs[0].metadata
    mock_source_operations.get_service_desk_request.assert_not_called()
    mock_source_operations.get_service_desk_sla.assert_not_called()


def test_jql_scope_keeps_and_indexes_non_service_desk_issues(
    jsm_connector: JiraServiceManagementConnector,
    mock_source_operations: MagicMock,
) -> None:
    """JQL-only configs also leave jira_project unset; their explicit query
    is the scope, so issues must not be dropped - only enrichment skips."""
    jsm_connector.jira_project = None
    jsm_connector.jql_query = "labels = portal"
    software_issue = _make_issue("ENG-3", project_key="ENG")
    software_issue["fields"]["project"]["projectTypeKey"] = "software"

    docs = _documents(jsm_connector, software_issue)

    assert len(docs) == 1
    assert docs[0].source is DocumentSource.JIRA_SERVICE_MANAGEMENT
    mock_source_operations.get_service_desk_request.assert_not_called()
    mock_source_operations.get_service_desk_sla.assert_not_called()


def test_everything_scope_filter_applies_to_slim_listing(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    """Pruning diffs slim IDs against the indexed set: the Everything-scope
    gate must hold there too, or moved issues keep stale JSM documents."""
    jsm_connector.jira_project = None
    jsm_connector.jql_query = None
    software_issue = _make_issue("ENG-4", project_key="ENG")
    software_issue["fields"]["project"]["projectTypeKey"] = "software"
    desk_issue = _make_issue("HELP-6")

    assert jsm_connector._include_issue_in_slim_listing(software_issue) is False
    assert jsm_connector._include_issue_in_slim_listing(desk_issue) is True

    # explicit scopes are exempt, same as indexing
    jsm_connector.jql_query = "labels = portal"
    assert jsm_connector._include_issue_in_slim_listing(software_issue) is True


def test_project_permissions_pass_through_to_jira_base(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    """Project permissions for JSM delegate directly to the base Jira connector
    and cache bare group IDs once per project (storage adds the source prefix)."""
    from onyx.access.models import ExternalAccess

    bare_access = ExternalAccess(
        external_user_emails={"agent@example.com"},
        external_user_group_ids={"support-agents", "other_group"},
        is_public=False,
    )

    with patch(
        "onyx.connectors.jira.connector.get_project_permissions",
        return_value=bare_access,
    ) as mock_perms:
        first = jsm_connector._get_project_permissions("HELP")
        second = jsm_connector._get_project_permissions("HELP")

    mock_perms.assert_called_once_with(
        source_operations=jsm_connector.source_operations,
        jira_project="HELP",
    )
    assert first is second
    assert first.external_user_group_ids == {
        "support-agents",
        "other_group",
    }


def test_malformed_portal_responses_do_not_drop_document(
    jsm_connector: JiraServiceManagementConnector,
    mock_source_operations: MagicMock,
) -> None:
    """Non-mapping portal/SLA responses or nested fields must skip only invalid
    enrichment fields while keeping valid sibling fields and the Jira document."""
    # Nested field is a string ("unavailable") while requestType is valid.
    mock_source_operations.get_service_desk_request.return_value = {
        "requestType": {"name": "Get IT help"},
        "currentStatus": "unavailable",
    }
    mock_source_operations.get_service_desk_sla.return_value = ["unexpected-list"]

    docs = _documents(jsm_connector, _make_issue("HELP-7"))
    assert len(docs) == 1
    assert docs[0].source is DocumentSource.JIRA_SERVICE_MANAGEMENT
    assert docs[0].metadata["request_type"] == "Get IT help"
    assert "portal_status" not in docs[0].metadata
    assert "sla_breached" not in docs[0].metadata

    # Top-level non-mapping request payload returned by gateway or _get_json.
    mock_source_operations.get_service_desk_request.return_value = ["top-level-list"]
    mock_source_operations.get_service_desk_sla.return_value = {
        "values": [{"ongoingCycle": {"breached": False}}]
    }

    docs2 = _documents(jsm_connector, _make_issue("HELP-8"))
    assert len(docs2) == 1
    assert docs2[0].source is DocumentSource.JIRA_SERVICE_MANAGEMENT
    assert "request_type" not in docs2[0].metadata
    assert "portal_status" not in docs2[0].metadata
    assert docs2[0].metadata["sla_breached"] == "false"


def test_get_service_desk_request_rejects_non_mapping_json() -> None:
    """Gateway must return None instead of leaking a top-level list/scalar payload."""
    from onyx.connectors.jira.source_operations import JiraSourceOperations

    client = MagicMock()
    client._get_json.return_value = ["not-a-mapping"]
    ops = JiraSourceOperations.__new__(JiraSourceOperations)
    ops._cached_client = client
    ops._cached_fast_client = client

    assert ops.get_service_desk_request(issue_key="IT-1") is None


def test_everything_scope_resolves_and_caches_omitted_project_type(
    jsm_connector: JiraServiceManagementConnector,
    mock_source_operations: MagicMock,
) -> None:
    """When issue omits projectTypeKey under Everything scope, resolve and cache
    via get_project consistently across indexing and slim listing."""
    jsm_connector.jira_project = None
    jsm_connector.jql_query = None

    def issue_without_type(key: str, project_key: str) -> dict[str, Any]:
        issue = _make_issue(key, project_key=project_key)
        issue["fields"]["project"].pop("projectTypeKey")
        return issue

    mock_source_operations.get_project.side_effect = [
        {"key": "SW", "projectTypeKey": "software"},
        {"key": "DESK", "projectTypeKey": "service_desk"},
    ]

    # Resolved software project -> dropped from indexing and slim listing; cached.
    sw_issue_1 = issue_without_type("SW-1", "SW")
    sw_issue_2 = issue_without_type("SW-2", "SW")
    assert _documents(jsm_connector, sw_issue_1) == []
    assert _documents(jsm_connector, sw_issue_2) == []
    assert jsm_connector._include_issue_in_slim_listing(sw_issue_1) is False

    # Resolved service_desk project -> indexed and included in slim listing; cached.
    desk_issue_1 = issue_without_type("DESK-1", "DESK")
    desk_issue_2 = issue_without_type("DESK-2", "DESK")
    assert len(_documents(jsm_connector, desk_issue_1)) == 1
    assert len(_documents(jsm_connector, desk_issue_2)) == 1
    assert jsm_connector._include_issue_in_slim_listing(desk_issue_1) is True

    assert mock_source_operations.get_project.call_args_list == [
        call(project_key="SW", fast=True),
        call(project_key="DESK", fast=True),
    ]


def test_everything_scope_drops_unresolvable_project_type(
    jsm_connector: JiraServiceManagementConnector,
    mock_source_operations: MagicMock,
) -> None:
    """Fail-closed under Everything scope when projectTypeKey cannot be determined,
    while preserving explicit Project/JQL scopes."""
    import requests

    jsm_connector.jira_project = None
    jsm_connector.jql_query = None

    missing_type = _make_issue("UNK-1", project_key="UNK")
    missing_type["fields"]["project"].pop("projectTypeKey")
    mock_source_operations.get_project.return_value = {"key": "UNK"}

    assert _documents(jsm_connector, missing_type) == []
    assert jsm_connector._include_issue_in_slim_listing(missing_type) is False

    failed_lookup = _make_issue("ERR-1", project_key="ERR")
    failed_lookup["fields"]["project"].pop("projectTypeKey")
    mock_source_operations.get_project.side_effect = requests.RequestException("boom")
    assert _documents(jsm_connector, failed_lookup) == []
    assert jsm_connector._include_issue_in_slim_listing(failed_lookup) is False

    # Explicit scope still indexes when projectTypeKey cannot be resolved.
    jsm_connector.jql_query = "project = ERR"
    docs = _documents(jsm_connector, failed_lookup)
    assert len(docs) == 1
    assert jsm_connector._include_issue_in_slim_listing(failed_lookup) is True
