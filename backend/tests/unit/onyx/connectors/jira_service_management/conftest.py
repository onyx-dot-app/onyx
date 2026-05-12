"""
Shared fixtures for Jira Service Management unit tests.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from jira import JIRA
from jira.resources import Issue

from onyx.connectors.jira.utils import JIRA_SERVER_API_VERSION
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)


# ---------------------------------------------------------------------------
# Basic value fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def jsm_base_url() -> str:
    return "https://example.atlassian.net"


@pytest.fixture
def jsm_project_key() -> str:
    return "HELP"


# ---------------------------------------------------------------------------
# Mock Jira client
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_jira_client() -> MagicMock:
    mock = MagicMock(spec=JIRA)
    mock._options = {"rest_api_version": JIRA_SERVER_API_VERSION}
    mock.search_issues = MagicMock(return_value=[])
    mock.project = MagicMock()
    mock.projects = MagicMock(return_value=[])
    mock.fields = MagicMock(return_value=[])
    return mock


# ---------------------------------------------------------------------------
# Connector fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def jsm_connector(
    jsm_base_url: str,
    jsm_project_key: str,
    mock_jira_client: MagicMock,
) -> Iterator[JiraServiceManagementConnector]:
    """Yield a JSM connector with a pre-wired mock Jira client.

    ``batch_size=2`` is passed via the constructor rather than patching the
    module-level ``_JIRA_FULL_PAGE_SIZE`` constant, which avoids relying on
    private internals of the base class that could be renamed or removed.
    The patch is still applied for completeness since the base class
    pagination logic reads that constant directly in some paths.
    """
    connector = JiraServiceManagementConnector(
        jira_base_url=jsm_base_url,
        project_key=jsm_project_key,
        comment_email_blacklist=[],
        labels_to_skip=[],
        batch_size=2,
    )
    connector._jira_client = mock_jira_client
    connector._jira_client.client_info = MagicMock(return_value=jsm_base_url)
    with patch("onyx.connectors.jira.connector.JIRA_FULL_PAGE_SIZE", 2):
        yield connector


# ---------------------------------------------------------------------------
# Issue factory helper
# ---------------------------------------------------------------------------


def make_mock_issue(
    key: str = "HELP-1",
    summary: str = "Need help",
    description: str = "Issue description",
    updated: str = "2024-01-01T12:00:00.000+0000",
    project_key: str = "HELP",
    project_name: str = "Help Desk",
    issuetype_name: str = "Service Request",
    labels: list[str] | None = None,
    extra_fields: dict[str, Any] | None = None,
) -> MagicMock:
    """Build a lightweight mock ``Issue`` object for use in unit tests.

    ``issue.fields`` is created with a spec derived from a dynamically
    generated class whose attributes exactly match the allow-list below.
    This means:

    * All legitimate reads (``issue.fields.summary``, etc.) succeed because
      the attribute name is declared on the spec class.
    * Any ``customfield_*`` that is NOT in ``extra_fields`` will raise
      ``AttributeError`` on read access, so ``getattr(issue.fields,
      field_id, None)`` — the pattern used by ``_get_raw_field`` — correctly
      returns ``None`` for missing fields instead of auto-creating a
      ``MagicMock`` that would silently attach garbage metadata to indexed
      documents.

    Using ``type("_FieldsSpec", (), {...})`` instead of passing the list
    directly to ``spec=`` ensures that MagicMock specs against the *class
    attributes* (our field names) rather than against the Python ``list``
    interface (``append``, ``pop``, etc.), which would be semantically
    wrong and fragile across ``unittest.mock`` versions.

    All JSM-specific attributes (``serviceDeskId``, ``requestType``) are
    explicitly pinned to ``None`` so that ``getattr`` calls inside the
    connector helpers return ``None`` rather than an auto-created
    ``MagicMock``.

    Any ``extra_fields`` are applied both to ``issue.raw["fields"]`` (for
    paths that read from the raw dict) and as ``setattr(issue.fields, …)``
    (for paths that use attribute access), keeping both representations in
    sync.
    """
    issue = MagicMock(spec=Issue)
    issue.key = key

    # Build the explicit allow-list so that:
    #   - every attribute set below is reachable (no AttributeError on write
    #     or subsequent read), and
    #   - any customfield_* NOT in extra_fields still raises AttributeError,
    #     keeping _get_raw_field's getattr(…, None) semantics intact.
    allowed_fields: list[str] = [
        "summary",
        "description",
        "updated",
        "labels",
        "created",
        "duedate",
        "resolutiondate",
        "issuetype",
        "project",
        "reporter",
        "assignee",
        "priority",
        "status",
        "resolution",
        "parent",
        "serviceDeskId",
        "requestType",
        *(extra_fields.keys() if extra_fields else []),
    ]

    # FIX: Build a proper class so MagicMock specs against our field names,
    # not against the Python list interface (append / pop / etc.).
    # Each attribute is set to None as a neutral sentinel; MagicMock only
    # uses the presence of the name on the class, not the value.
    _FieldsSpec = type("_FieldsSpec", (), {f: None for f in allowed_fields})
    issue.fields = MagicMock(spec=_FieldsSpec)

    issue.fields.summary = summary
    issue.fields.description = description
    issue.fields.updated = updated
    issue.fields.labels = labels or []
    issue.fields.created = updated
    issue.fields.duedate = None
    issue.fields.resolutiondate = None

    # issuetype
    issue.fields.issuetype = MagicMock()
    issue.fields.issuetype.name = issuetype_name

    # project
    issue.fields.project = MagicMock()
    issue.fields.project.key = project_key
    issue.fields.project.name = project_name

    # reporter / assignee — minimal
    issue.fields.reporter = MagicMock()
    issue.fields.reporter.displayName = "Reporter Name"
    issue.fields.reporter.emailAddress = "reporter@example.com"

    issue.fields.assignee = None
    issue.fields.priority = None
    issue.fields.status = MagicMock()
    issue.fields.status.name = "Open"
    issue.fields.resolution = None
    issue.fields.parent = None

    # raw dict (used by extract_text_from_adf and raw-field lookups)
    issue.raw = {
        "fields": {
            "description": description,
            **(extra_fields or {}),
        }
    }

    # Explicitly pin JSM-specific fields to None so getattr() calls in
    # _get_service_desk_id / _get_raw_field return None, not auto-created MagicMocks.
    issue.fields.serviceDeskId = None
    issue.fields.requestType = None

    # Apply extra_fields as attributes too so both reading paths are consistent.
    if extra_fields:
        for field_name, field_value in extra_fields.items():
            setattr(issue.fields, field_name, field_value)

    return issue
