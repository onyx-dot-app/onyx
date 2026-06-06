import time
from unittest.mock import MagicMock
from unittest.mock import patch

from jira import JIRA
from jira.resources import Issue

from onyx.configs.constants import DocumentSource
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)
from onyx.connectors.models import Document
from onyx.connectors.models import TextSection
from tests.unit.onyx.connectors.utils import load_everything_from_checkpoint_connector


def _build_mock_issue() -> MagicMock:
    issue = MagicMock(spec=Issue)
    issue.key = "JSM-1"
    issue.fields = MagicMock()
    issue.fields.summary = "Customer request"
    issue.fields.updated = "2025-06-06T00:00:00.000+0000"
    issue.fields.description = "Help me please"
    issue.fields.labels = []
    issue.fields.reporter = None
    issue.fields.assignee = None
    issue.fields.priority = None
    issue.fields.status = None
    issue.fields.resolution = None
    issue.fields.project = MagicMock()
    issue.fields.project.key = "JSM"
    issue.fields.project.name = "Jira Service Management"
    issue.fields.issuetype = MagicMock()
    issue.fields.issuetype.name = "Task"
    issue.fields.parent = None
    issue.raw = {"fields": {"description": issue.fields.description}}
    return issue


def test_jira_service_management_connector_uses_distinct_source(
    jira_base_url: str,
) -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url=jira_base_url,
        project_key="JSM",
    )

    mock_client = MagicMock(spec=JIRA)
    mock_client._options = {"rest_api_version": "2"}
    mock_client.search_issues.side_effect = [[_build_mock_issue()], []]
    connector._jira_client = mock_client

    with patch(
        "onyx.connectors.jira.connector.process_jira_issue"
    ) as mock_process:
        mock_process.return_value = Document(
            id="https://jira.example.com/browse/JSM-1",
            sections=[
                TextSection(
                    link="https://jira.example.com/browse/JSM-1",
                    text="Help me please",
                )
            ],
            source=DocumentSource.JIRA_SERVICE_MANAGEMENT,
            semantic_identifier="JSM-1: Customer request",
            metadata={},
        )

        outputs = load_everything_from_checkpoint_connector(
            connector,
            0,
            time.time(),
        )
        docs = [
            item
            for batch in outputs
            for item in batch.items
            if isinstance(item, Document)
        ]

    assert docs
    assert docs[0].source == DocumentSource.JIRA_SERVICE_MANAGEMENT
    assert mock_process.call_count == 1
    assert mock_process.call_args.kwargs["source"] == DocumentSource.JIRA_SERVICE_MANAGEMENT
