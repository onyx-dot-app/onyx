"""Jira Service Management Connector for indexing Jira Service Management tickets."""

import copy
import os
from collections.abc import Generator
from datetime import datetime
from datetime import timezone
from typing import Any

import requests
from jira import JIRA
from jira.exceptions import JIRAError
from typing_extensions import override

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import (
    ConnectorMissingCredentialError,
    ValidationError,
)
from onyx.connectors.interfaces import (
    CheckpointedConnector,
    CheckpointOutput,
    SecondsSinceUnixEpoch,
)
from onyx.connectors.models import ConnectorCheckpoint
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import Document
from onyx.connectors.models import TextSection
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger

logger = setup_logger(__name__)

# Jira Service Management ticket types
JSM_ISSUE_TYPES = [
    "Service Request",
    "Incident",
    "Problem",
    "Change",
    "Service Task",
]


class JiraServiceManagementCheckpoint(ConnectorCheckpoint):
    """Checkpoint for Jira Service Management connector."""

    # Track current position
    offset: int | None = None
    # Track last updated date for incremental sync
    last_updated: str | None = None


class JiraServiceManagementConnector(CheckpointedConnector[JiraServiceManagementCheckpoint]):
    """Connector for Jira Service Management (JSM) tickets.

    This connector indexes Service Request, Incident, Problem, Change, and Service Task
    tickets from Jira Service Management projects.
    """

    def __init__(
        self,
        jsm_url: str,
        jsm_email: str | None,
        jsm_api_token: str | None,
        jsm_project_key: str,
        batch_size: int = INDEX_BATCH_SIZE,
        index_heartbeat: IndexingHeartbeatInterface | None = None,
    ) -> None:
        """Initialize Jira Service Management connector.

        Args:
            jsm_url: Jira Service Management URL (e.g., https://your-company.atlassian.net)
            jsm_email: Email for Jira API authentication
            jsm_api_token: API token for Jira authentication
            jsm_project_key: Project key for the JSM project
            batch_size: Number of tickets to process per batch
            index_heartbeat: Optional heartbeat for long-running indexing
        """
        self.jsm_url = jsm_url.rstrip("/")
        self.jsm_email = jsm_email or os.environ.get("JIRA_SERVICE_MGMT_EMAIL", "")
        self.jsm_api_token = jsm_api_token or os.environ.get(
            "JIRA_SERVICE_MGMT_API_TOKEN", ""
        )
        self.jsm_project_key = jsm_project_key
        self.batch_size = batch_size
        self.index_heartbeat = index_heartbeat

        if not self.jsm_email or not self.jsm_api_token:
            raise ConnectorMissingCredentialError("Jira Service Management")

        self._jira_client: JIRA | None = None

    @property
    def jira_client(self) -> JIRA:
        """Get or create Jira client."""
        if self._jira_client is None:
            self._jira_client = JIRA(
                server=self.jsm_url,
                basic_auth=(self.jsm_email, self.jsm_api_token),
            )
        return self._jira_client

    @override
    def load_credentials(
        self,
    ) -> dict[str, Any] | None:
        """Load credentials for credential lookups."""
        return {
            "jsm_url": self.jsm_url,
            "email": self.jsm_email,
            "api_token": self.jsm_api_token,
            "project_key": self.jsm_project_key,
        }

    def _build_jql(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
    ) -> str:
        """Build JQL query for JSM tickets."""
        jql_parts = [
            f'project = "{self.jsm_project_key}"',
            'type IN ("Service Request", "Incident", "Problem", "Change", "Service Task")',
        ]

        # Add time range filter if timestamps provided
        if start:
            start_dt = datetime.fromtimestamp(start, tz=timezone.utc)
            jql_parts.append(f'created >= "{start_dt.isoformat()}"')

        if end:
            end_dt = datetime.fromtimestamp(end, tz=timezone.utc)
            jql_parts.append(f'created <= "{end_dt.isoformat()}"')

        return " AND ".join(jql_parts)

    def _issue_to_document(
        self,
        issue: Any,
    ) -> Document:
        """Convert Jira issue to Document."""
        fields = issue.fields

        # Build text content
        text_parts = []

        # Title and key
        title = f"{issue.key}: {fields.summary}"
        text_parts.append(title)

        # Description
        if hasattr(fields, "description") and fields.description:
            desc = fields.description
            if isinstance(desc, str):
                text_parts.append(desc)
            elif hasattr(desc, "rawText"):
                text_parts.append(desc.rawText)

        # Status
        if hasattr(fields, "status") and fields.status:
            text_parts.append(f"Status: {fields.status.name}")

        # Priority
        if hasattr(fields, "priority") and fields.priority:
            text_parts.append(f"Priority: {fields.priority.name}")

        # Issue type
        if hasattr(fields, "issuetype") and fields.issuetype:
            text_parts.append(f"Type: {fields.issuetype.name}")

        # Request type (for Service Requests)
        if hasattr(fields, "request_type") and fields.request_type:
            rt = fields.request_type
            text_parts.append(f"Request Type: {rt.name if hasattr(rt, 'name') else str(rt)}")

        # Assignee
        if hasattr(fields, "assignee") and fields.assignee:
            text_parts.append(f"Assignee: {fields.assignee.displayName}")

        # Reporter
        if hasattr(fields, "reporter") and fields.reporter:
            text_parts.append(f"Reporter: {fields.reporter.displayName}")

        # Created/Updated
        if hasattr(fields, "created") and fields.created:
            text_parts.append(f"Created: {fields.created}")
        if hasattr(fields, "updated") and fields.updated:
            text_parts.append(f"Updated: {fields.updated}")

        # SLA information (if available)
        if hasattr(fields, "sla") and fields.sla:
            for sla in fields.sla:
                sla_info = f"SLA: {sla.get('name', 'Unknown')}"
                if sla.get("status"):
                    sla_info += f" - {sla['status']}"
                text_parts.append(sla_info)

        # Portal link
        portal_url = f"{self.jsm_url}/servicedesk/customer/portal/{self.jsm_project_key}/{issue.key}"

        text = "\n\n".join(text_parts)

        # Build metadata
        metadata = {
            "key": issue.key,
            "issue_type": fields.issuetype.name if hasattr(fields, "issuetype") and fields.issuetype else None,
            "status": fields.status.name if hasattr(fields, "status") and fields.status else None,
            "priority": fields.priority.name if hasattr(fields, "priority") and fields.priority else None,
        }

        return Document(
            id=f"jira_service_management_{issue.key}",
            source=DocumentSource.JIRA_SERVICE_MANAGEMENT,
            title=title,
            sections=[TextSection(link=portal_url, text=text)],
            metadata=metadata,
        )

    @override
    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: JiraServiceManagementCheckpoint,
    ) -> CheckpointOutput[JiraServiceManagementCheckpoint]:
        """Load documents from Jira Service Management starting from checkpoint.

        Yields Document, HierarchyNode, or ConnectorFailure objects.
        Returns the new checkpoint.
        """
        jql = self._build_jql(start, end)
        offset = checkpoint.offset or 0

        while True:
            try:
                # Search for issues
                issues = self.jira_client.search_issues(
                    jql,
                    startAt=offset,
                    maxResults=self.batch_size,
                    expand="renderedFields",
                )

                if not issues:
                    break

                # Process each issue
                for issue in issues:
                    try:
                        doc = self._issue_to_document(issue)
                        yield doc
                    except Exception as e:
                        logger.error(f"Error processing issue {issue.key}: {e}")
                        yield ConnectorFailure(
                            document_id=f"jira_service_management_{issue.key}",
                            document_link=f"{self.jsm_url}/browse/{issue.key}",
                            error_message=str(e),
                        )

                # Check if there are more results
                if len(issues) < self.batch_size:
                    break

                # Update offset for next batch
                offset += len(issues)

                # Heartbeat
                if self.index_heartbeat:
                    self.index_heartbeat.should_continue()

            except JIRAError as e:
                logger.error(f"Jira API error: {e}")
                raise ValidationError(f"Jira API error: {e}")
            except Exception as e:
                logger.error(f"Error loading JSM tickets: {e}")
                raise ValidationError(f"Error loading JSM tickets: {e}")

        # Return final checkpoint
        return JiraServiceManagementCheckpoint(
            offset=0,
            last_updated=checkpoint.last_updated,
            has_more=False,
        )

    @override
    def validate_and_process_credentials(
        self,
        credentials: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Validate credentials and return config and credential details."""
        jsm_url = credentials.get("jsm_url")
        email = credentials.get("email")
        api_token = credentials.get("api_token")
        project_key = credentials.get("project_key")

        if not all([jsm_url, email, api_token, project_key]):
            raise ConnectorMissingCredentialError("Jira Service Management")

        # Test connection
        try:
            client = JIRA(
                server=jsm_url,
                basic_auth=(email, api_token),
            )
            # Verify project exists
            project = client.project(project_key)
            logger.info(f"Successfully connected to JSM project: {project.name}")
        except JIRAError as e:
            raise ValidationError(f"Failed to connect to Jira: {e}")

        return credentials, credentials
