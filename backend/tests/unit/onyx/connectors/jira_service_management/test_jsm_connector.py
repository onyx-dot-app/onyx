"""Unit tests for the Jira Service Management connector.

These mock the underlying Jira client entirely — no network calls, no
running Onyx services. They lock in the JSM-specific behavior layered on
top of `JiraConnector`:

  * issue-type filter injected into JQL by default
  * documents tagged with the `JIRA_SERVICE_MANAGEMENT` source
  * user-provided `jql_query` overrides the auto-filter
"""

from typing import Any
from unittest.mock import MagicMock

from jira.resources import Issue

from onyx.configs.constants import DocumentSource
from onyx.connectors.jira_service_management.connector import (
    _build_jsm_issue_type_clause,
)
from onyx.connectors.jira_service_management.connector import (
    DEFAULT_JSM_ISSUE_TYPES,
)
from onyx.connectors.jira_service_management.connector import JsmConnector
from onyx.connectors.jira_service_management.connector import process_jsm_issue


# ---------------------------------------------------------------------------
# JQL clause builder
# ---------------------------------------------------------------------------


def test_build_jsm_issue_type_clause_default_types() -> None:
    clause = _build_jsm_issue_type_clause(DEFAULT_JSM_ISSUE_TYPES)
    assert clause.startswith("issuetype in (")
    assert '"Service Request"' in clause
    assert '"Incident"' in clause
    assert '"Problem"' in clause
    assert '"Change"' in clause


def test_build_jsm_issue_type_clause_empty() -> None:
    assert _build_jsm_issue_type_clause(tuple()) == ""


def test_build_jsm_issue_type_clause_single() -> None:
    assert _build_jsm_issue_type_clause(("Incident",)) == 'issuetype in ("Incident")'


def test_build_jsm_issue_type_clause_quotes_each_type() -> None:
    clause = _build_jsm_issue_type_clause(("Service Request", "Incident"))
    # Each entry must be individually quoted; otherwise multi-word types break JQL.
    assert '"Service Request"' in clause
    assert '"Incident"' in clause


# ---------------------------------------------------------------------------
# JsmConnector construction
# ---------------------------------------------------------------------------


def test_jsm_connector_default_injects_issue_type_filter() -> None:
    """With no explicit jql_query, the default JSM issue-type filter is used."""
    conn = JsmConnector(jira_base_url="https://example.atlassian.net")
    assert conn.jql_query is not None
    assert conn.jql_query.startswith("issuetype in (")
    assert '"Service Request"' in conn.jql_query


def test_jsm_connector_explicit_jql_query_overrides_default() -> None:
    """When the user provides jql_query, it's used as-is — no auto-injection."""
    custom = "project = ITSM AND status != Done"
    conn = JsmConnector(
        jira_base_url="https://example.atlassian.net",
        jql_query=custom,
    )
    assert conn.jql_query == custom
    # No issue-type clause should be auto-prepended.
    assert "issuetype" not in conn.jql_query


def test_jsm_connector_custom_issue_types_replace_defaults() -> None:
    """`jsm_issue_types` lets the caller scope to a subset of JSM types."""
    conn = JsmConnector(
        jira_base_url="https://example.atlassian.net",
        jsm_issue_types=("Incident",),
    )
    assert conn.jql_query == 'issuetype in ("Incident")'
    assert conn.jsm_issue_types == ("Incident",)


def test_jsm_connector_empty_issue_types_disables_filter() -> None:
    """An explicit empty tuple disables the auto-filter (acts like vanilla Jira)."""
    conn = JsmConnector(
        jira_base_url="https://example.atlassian.net",
        jsm_issue_types=tuple(),
    )
    assert conn.jql_query is None
    assert conn.jsm_issue_types == tuple()


def test_jsm_connector_preserves_base_attrs() -> None:
    """Sanity check: parent JiraConnector attrs are correctly initialized."""
    conn = JsmConnector(
        jira_base_url="https://example.atlassian.net/",  # trailing slash trimmed
        project_key="ITSM",
    )
    assert conn.jira_base == "https://example.atlassian.net"
    assert conn.jira_project == "ITSM"


# ---------------------------------------------------------------------------
# process_jsm_issue document tagging
# ---------------------------------------------------------------------------


def _make_issue(key: str = "ITSM-1") -> Issue:
    """Build a minimal Issue object compatible with `process_jira_issue`.

    All optional fields (reporter, assignee, priority, etc.) are set to None
    so `best_effort_get_field_from_issue` returns None and the record-builder
    skips the optional metadata branches cleanly.
    """
    raw: dict[str, Any] = {
        "id": "10001",
        "key": key,
        "fields": {
            "summary": "Test issue",
            "description": "A test JSM ticket.",
            "labels": [],
            "comment": {"comments": []},
            "updated": "2025-01-15T10:00:00.000+0000",
            "project": {"key": "ITSM", "name": "ITSM"},
            "reporter": None,
            "assignee": None,
            "priority": None,
            "status": None,
            "resolution": None,
            "created": None,
            "duedate": None,
            "issuetype": None,
            "parent": None,
            "resolutiondate": None,
        },
    }
    issue = MagicMock(spec=Issue)
    issue.key = key
    issue.raw = raw
    # Build a fields object that returns None for optional attrs (so the
    # `best_effort_get_field_from_issue` helper resolves them to None instead
    # of returning the default MagicMock auto-attr).
    fields = MagicMock(
        summary=raw["fields"]["summary"],
        description=raw["fields"]["description"],
        labels=[],
        updated=raw["fields"]["updated"],
        reporter=None,
        assignee=None,
        priority=None,
        status=None,
        resolution=None,
        created=None,
        duedate=None,
        issuetype=None,
        parent=None,
        resolutiondate=None,
    )
    fields.comment = MagicMock()
    fields.comment.comments = []
    issue.fields = fields
    return issue


def test_process_jsm_issue_tags_source_as_jsm() -> None:
    """The returned Document should carry the JIRA_SERVICE_MANAGEMENT source."""
    issue = _make_issue("ITSM-42")
    doc = process_jsm_issue(
        jira_base_url="https://example.atlassian.net",
        issue=issue,
    )
    assert doc is not None
    assert doc.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
    # Sanity: title and id still reflect the underlying issue.
    assert "ITSM-42" in doc.semantic_identifier
    assert doc.id.endswith("/browse/ITSM-42")


def test_process_jsm_issue_passes_through_skip_logic() -> None:
    """Labels-to-skip handling delegates to the base process_jira_issue."""
    issue = _make_issue()
    issue.fields.labels = ["sensitive"]
    doc = process_jsm_issue(
        jira_base_url="https://example.atlassian.net",
        issue=issue,
        labels_to_skip={"sensitive"},
    )
    assert doc is None
