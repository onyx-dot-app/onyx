from typing import Any

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.jira.connector import process_jira_issue
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)


@pytest.fixture
def issue_fixture() -> dict[str, Any]:
    """A raw issue as the Jira REST API returns it."""
    return {
        "id": "1",
        "key": "JSM-1",
        "fields": {
            "summary": "Test summary",
            "description": "Test description",
            "labels": [],
            "created": "2024-01-01T00:00:00.000+0000",
            "updated": "2024-01-01T00:00:00.000+0000",
            "project": {"key": "JSM", "name": "Jira Service Management"},
            "comment": {"comments": []},
        },
    }


def test_jsm_connector_source() -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://example.atlassian.net",
    )
    assert connector.document_source == DocumentSource.JIRA_SERVICE_MANAGEMENT


def test_jsm_process_issue_emits_jsm_source(issue_fixture: dict[str, Any]) -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://example.atlassian.net",
    )

    doc = process_jira_issue(
        jira_base_url=connector.jira_base,
        issue=issue_fixture,
        document_source=connector.document_source,
    )

    assert doc is not None
    assert doc.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
