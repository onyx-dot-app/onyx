"""
Jira Service Management (JSM) Connector for Onyx.

Pulls service desk tickets from a Jira Service Management project.
JSM issues are standard Jira issues with additional metadata (request type,
service desk name, SLA). This connector subclasses the existing JiraConnector
and layers JSM-specific configuration and metadata extraction on top.

Reference: https://github.com/onyx-dot-app/onyx/issues/2281
"""

from datetime import datetime, timezone

from jira.resources import Issue
from typing_extensions import override

from onyx.configs.app_configs import INDEX_BATCH_SIZE, JIRA_CONNECTOR_MAX_TICKET_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.miscellaneous_utils import time_str_to_utc
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.jira.connector import JiraConnector
from onyx.connectors.jira.utils import (
    best_effort_basic_expert_info,
    best_effort_get_field_from_issue,
    build_jira_url,
    extract_text_from_adf,
    get_comment_strs,
)
from onyx.connectors.models import Document, TextSection
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Common custom field IDs used by JSM for request type
_REQUEST_TYPE_FIELD_IDS = (
    "customfield_10010",
    "customfield_10001",
    "customfield_10000",
)


def _extract_request_type(issue: Issue) -> str | None:
    """Best-effort extraction of the JSM request type from an issue."""
    for field_id in _REQUEST_TYPE_FIELD_IDS:
        value = best_effort_get_field_from_issue(issue, field_id)
        if value is not None:
            if isinstance(value, dict):
                return value.get("name") or value.get("value")
            if isinstance(value, str):
                return value
    # Fallback: issue type name
    issuetype = best_effort_get_field_from_issue(issue, "issuetype")
    if issuetype is not None:
        if hasattr(issuetype, "name"):
            return issuetype.name
        if isinstance(issuetype, dict):
            return issuetype.get("name")
    return None


class JiraServiceManagementConnector(JiraConnector):
    """
    Jira Service Management connector.

    Extends the standard Jira connector with JSM-specific behaviour:
    - Uses DocumentSource.JIRA_SERVICE_MANAGEMENT so the connector
      appears as a separate source in the Onyx UI.
    - Enriches documents with JSM request-type metadata.
    - Optionally restricts indexing to specific JSM issue types.
    """

    def __init__(
        self,
        jira_base_url: str,
        project_key: str | None = None,
        comment_email_blacklist: list[str] | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
        labels_to_skip: list[str] | None = None,
        jql_query: str | None = None,
        scoped_token: bool = False,
        # JSM-specific
        include_request_types: list[str] | None = None,
    ) -> None:
        super().__init__(
            jira_base_url=jira_base_url,
            project_key=project_key,
            comment_email_blacklist=comment_email_blacklist,
            batch_size=batch_size,
            labels_to_skip=labels_to_skip or [],
            jql_query=jql_query,
            scoped_token=scoped_token,
        )
        self.include_request_types = include_request_types

    @override
    def _get_jql_query(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> str:
        """Build JQL for JSM issues within the time window."""
        start_date = datetime.fromtimestamp(start, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M"
        )
        end_date = datetime.fromtimestamp(end, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M"
        )
        time_jql = f"updated >= '{start_date}' AND updated <= '{end_date}'"

        if self.jql_query:
            return f"({self.jql_query}) AND {time_jql}"

        if self.jira_project:
            project_clause = f"project = {self.quoted_jira_project}"
            jql = f"{project_clause} AND {time_jql}"
        else:
            jql = time_jql

        # Optionally restrict to specific JSM issue types
        if self.include_request_types:
            types_str = ", ".join(f'"{t}"' for t in self.include_request_types)
            jql = f"{jql} AND issuetype in ({types_str})"

        return jql

    def _process_issue_as_jsm_ticket(self, issue: Issue) -> Document | None:
        """Process a Jira issue as a JSM ticket with JSM metadata."""
        if self.labels_to_skip:
            if any(label in issue.fields.labels for label in self.labels_to_skip):
                logger.info(
                    "Skipping %s - label in skip list.",
                    issue.key,
                )
                return None

        # Build ticket body
        if isinstance(issue.fields.description, str):
            description = issue.fields.description
        else:
            description = extract_text_from_adf(
                issue.raw["fields"].get("description")
            )

        comments = get_comment_strs(
            issue=issue,
            comment_email_blacklist=self.comment_email_blacklist,
        )
        ticket_content = f"{description}\n" + "\n".join(
            [f"Comment: {c}" for c in comments if c]
        )

        if len(ticket_content.encode("utf-8")) > JIRA_CONNECTOR_MAX_TICKET_SIZE:
            logger.info("Skipping %s - exceeds max ticket size.", issue.key)
            return None

        page_url = build_jira_url(self.jira_base, issue.key)
        metadata_dict: dict[str, str | list[str]] = {}
        metadata_dict["key"] = issue.key

        # JSM-specific: request type
        request_type = _extract_request_type(issue)
        if request_type:
            metadata_dict["request_type"] = request_type

        # Standard fields
        for field_name in ("priority", "status", "resolution", "issuetype"):
            val = best_effort_get_field_from_issue(issue, field_name)
            if val is not None:
                metadata_dict[field_name] = (
                    val.name if hasattr(val, "name") else str(val)
                )

        if labels := best_effort_get_field_from_issue(issue, "labels"):
            metadata_dict["labels"] = labels

        for field_name in ("created", "updated", "duedate"):
            val = best_effort_get_field_from_issue(issue, field_name)
            if val:
                metadata_dict[field_name] = val

        project = best_effort_get_field_from_issue(issue, "project")
        if project is not None:
            metadata_dict["project_name"] = (
                project.name if hasattr(project, "name") else None
            )
            metadata_dict["project"] = (
                project.key if hasattr(project, "key") else None
            )

        # People
        people: set = set()
        reporter = best_effort_get_field_from_issue(issue, "reporter")
        if reporter and (info := best_effort_basic_expert_info(reporter)):
            people.add(info)
            metadata_dict["reporter"] = info.get_semantic_name()

        assignee = best_effort_get_field_from_issue(issue, "assignee")
        if assignee and (info := best_effort_basic_expert_info(assignee)):
            people.add(info)
            metadata_dict["assignee"] = info.get_semantic_name()

        return Document(
            id=page_url,
            sections=[TextSection(link=page_url, text=ticket_content)],
            source=DocumentSource.JIRA_SERVICE_MANAGEMENT,
            semantic_identifier=f"{issue.key}: {issue.fields.summary}",
            title=f"{issue.key} {issue.fields.summary}",
            doc_updated_at=time_str_to_utc(issue.fields.updated),
            primary_owners=list(people) or None,
            metadata=metadata_dict,
        )

    @override
    def validate_connector_settings(self) -> None:
        """Validate JSM connector settings (delegates to Jira base validation)."""
        super().validate_connector_settings()
