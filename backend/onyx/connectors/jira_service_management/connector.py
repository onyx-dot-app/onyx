from typing import Any

from jira.resources import Issue

from onyx.configs.app_configs import (
    INDEX_BATCH_SIZE,
    JIRA_CONNECTOR_LABELS_TO_SKIP,
    JIRA_CONNECTOR_MAX_TICKET_SIZE,
)
from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.miscellaneous_utils import (
    time_str_to_utc,
)
from onyx.connectors.exceptions import (
    ConnectorValidationError,
)
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import (
    ConnectorMissingCredentialError,
    Document,
    TextSection,
)
from onyx.connectors.jira.connector import (
    _FIELD_ASSIGNEE,
    _FIELD_ASSIGNEE_EMAIL,
    _FIELD_CREATED,
    _FIELD_DUEDATE,
    _FIELD_ISSUETYPE,
    _FIELD_KEY,
    _FIELD_LABELS,
    _FIELD_PARENT,
    _FIELD_PRIORITY,
    _FIELD_PROJECT,
    _FIELD_PROJECT_NAME,
    _FIELD_REPORTER,
    _FIELD_REPORTER_EMAIL,
    _FIELD_RESOLUTION,
    _FIELD_RESOLUTION_DATE,
    _FIELD_RESOLUTION_DATE_KEY,
    _FIELD_STATUS,
    _FIELD_UPDATED,
    JiraConnector,
)
from onyx.connectors.jira.utils import (
    best_effort_basic_expert_info,
    best_effort_get_field_from_issue,
    build_jira_url,
    extract_text_from_adf,
)
from onyx.connectors.jira_service_management.utils import (
    FIELD_CUSTOMER_REQUEST_TYPE,
    FIELD_ORGANIZATIONS,
    FIELD_SLA_STATUS,
    extract_customer_request_type,
    extract_organizations,
    extract_sla_info,
    get_jsm_comment_strs,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()


class JiraServiceManagementConnector(JiraConnector):
    def __init__(
        self,
        jira_base_url: str,
        project_key: str,
        comment_email_blacklist: list[str] | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
        labels_to_skip: list[str] = JIRA_CONNECTOR_LABELS_TO_SKIP,
        jql_query: str | None = None,
        scoped_token: bool = False,
        include_attachments: bool = False,
        include_internal_comments: bool = False,
    ) -> None:
        if jql_query and project_key:
            if "project" not in jql_query.lower():
                jql_query = f"project = '{project_key}' AND ({jql_query})"

        super().__init__(
            jira_base_url=jira_base_url,
            project_key=project_key,
            comment_email_blacklist=comment_email_blacklist,
            batch_size=batch_size,
            labels_to_skip=labels_to_skip,
            jql_query=jql_query,
            scoped_token=scoped_token,
        )
        self.source = DocumentSource.JIRA_SERVICE_MANAGEMENT
        self.include_attachments = include_attachments
        self.include_internal_comments = include_internal_comments

    def _get_jql_query(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> str:
        base_jql = super()._get_jql_query(start, end)
        if self.labels_to_skip:
            skipped = ", ".join(f'"{lbl}"' for lbl in self.labels_to_skip)
            return f"({base_jql}) AND (labels is EMPTY OR labels not in ({skipped}))"
        return base_jql

    def validate_connector_settings(self) -> None:
        if self._jira_client is None:
            raise ConnectorMissingCredentialError("Jira Service Management")

        if not self.jira_project or not self.jira_project.strip():
            raise ConnectorValidationError(
                "A Jira Service Management project key is required."
            )

        # Validate project exists
        try:
            proj = self.jira_client.project(self.jira_project)
            proj_type = getattr(proj, "projectTypeKey", None)
            if proj_type and proj_type != "service_desk":
                raise ConnectorValidationError(
                    f"Project '{self.jira_project}' has type '{proj_type}', expected 'service_desk' for Jira Service Management."
                )
        except Exception as e:
            self._handle_jira_connector_settings_error(e)

        # If custom JQL query is provided, validate it
        if self.jql_query:
            try:
                from onyx.connectors.jira.connector import _perform_jql_search

                next(
                    iter(
                        _perform_jql_search(
                            jira_client=self.jira_client,
                            jql=self.jql_query,
                            start=0,
                            max_results=1,
                            all_issue_ids=[],
                        )
                    ),
                    None,
                )
            except Exception as e:
                self._handle_jira_connector_settings_error(e)

    def _process_issue(
        self,
        issue: Issue,
        parent_hierarchy_raw_node_id: str | None = None,
    ) -> Document | None:
        if self.labels_to_skip:
            issue_labels = getattr(issue.fields, "labels", [])
            if any(label in issue_labels for label in self.labels_to_skip):
                logger.info(
                    "Skipping %s because it has a label to skip. Found labels: %s.",
                    issue.key,
                    issue_labels,
                )
                return None

        # Extract description
        raw_fields = getattr(issue, "raw", {}).get("fields", {})
        raw_description = raw_fields.get("description")
        if isinstance(issue.fields.description, str):
            description = issue.fields.description
        elif raw_description:
            description = extract_text_from_adf(raw_description)
        else:
            description = ""

        # Extract comments distinguishing internal agent notes
        comments = get_jsm_comment_strs(
            issue=issue,
            comment_email_blacklist=self.comment_email_blacklist,
            include_internal_comments=self.include_internal_comments,
        )

        # Extract JSM-specific metadata
        request_type = extract_customer_request_type(issue)
        organizations = extract_organizations(issue)
        sla_info = extract_sla_info(issue)

        # Build content text
        content_parts = []
        if request_type:
            content_parts.append(f"Request Type: {request_type}")
        if organizations:
            content_parts.append(f"Organizations: {', '.join(organizations)}")
        if sla_info:
            sla_strs = [f"{name}: {status}" for name, status in sla_info.items()]
            content_parts.append(f"SLAs: {'; '.join(sla_strs)}")

        if description:
            content_parts.append(f"\nDescription:\n{description}")

        if comments:
            comments_text = "\n".join(f"Comment: {c}" for c in comments if c)
            content_parts.append(f"\nComments:\n{comments_text}")

        ticket_content = "\n".join(content_parts).strip()

        # Check ticket size
        if len(ticket_content.encode("utf-8")) > JIRA_CONNECTOR_MAX_TICKET_SIZE:
            logger.info(
                "Skipping %s because it exceeds the maximum size of %s bytes.",
                issue.key,
                JIRA_CONNECTOR_MAX_TICKET_SIZE,
            )
            return None

        page_url = build_jira_url(self.jira_base, issue.key)

        metadata_dict: dict[str, Any] = {}
        people = set()

        creator = best_effort_get_field_from_issue(issue, _FIELD_REPORTER)
        if creator is not None and (
            basic_expert_info := best_effort_basic_expert_info(creator)
        ):
            people.add(basic_expert_info)
            metadata_dict[_FIELD_REPORTER] = basic_expert_info.get_semantic_name()
            if email := basic_expert_info.get_email():
                metadata_dict[_FIELD_REPORTER_EMAIL] = email

        assignee = best_effort_get_field_from_issue(issue, _FIELD_ASSIGNEE)
        if assignee is not None and (
            basic_expert_info := best_effort_basic_expert_info(assignee)
        ):
            people.add(basic_expert_info)
            metadata_dict[_FIELD_ASSIGNEE] = basic_expert_info.get_semantic_name()
            if email := basic_expert_info.get_email():
                metadata_dict[_FIELD_ASSIGNEE_EMAIL] = email

        metadata_dict[_FIELD_KEY] = issue.key
        if priority := best_effort_get_field_from_issue(issue, _FIELD_PRIORITY):
            metadata_dict[_FIELD_PRIORITY] = (
                priority.name if hasattr(priority, "name") else str(priority)
            )
        if status := best_effort_get_field_from_issue(issue, _FIELD_STATUS):
            metadata_dict[_FIELD_STATUS] = (
                status.name if hasattr(status, "name") else str(status)
            )
        if resolution := best_effort_get_field_from_issue(issue, _FIELD_RESOLUTION):
            metadata_dict[_FIELD_RESOLUTION] = (
                resolution.name if hasattr(resolution, "name") else str(resolution)
            )
        if labels := best_effort_get_field_from_issue(issue, _FIELD_LABELS):
            metadata_dict[_FIELD_LABELS] = labels
        if created := best_effort_get_field_from_issue(issue, _FIELD_CREATED):
            metadata_dict[_FIELD_CREATED] = created
        if updated := best_effort_get_field_from_issue(issue, _FIELD_UPDATED):
            metadata_dict[_FIELD_UPDATED] = updated
        if duedate := best_effort_get_field_from_issue(issue, _FIELD_DUEDATE):
            metadata_dict[_FIELD_DUEDATE] = duedate
        if issuetype := best_effort_get_field_from_issue(issue, _FIELD_ISSUETYPE):
            metadata_dict[_FIELD_ISSUETYPE] = (
                issuetype.name if hasattr(issuetype, "name") else str(issuetype)
            )
        if resolutiondate := best_effort_get_field_from_issue(
            issue, _FIELD_RESOLUTION_DATE
        ):
            metadata_dict[_FIELD_RESOLUTION_DATE_KEY] = resolutiondate

        parent = best_effort_get_field_from_issue(issue, _FIELD_PARENT)
        if parent is not None:
            metadata_dict[_FIELD_PARENT] = (
                parent.key if hasattr(parent, "key") else str(parent)
            )

        project = best_effort_get_field_from_issue(issue, _FIELD_PROJECT)
        if project is not None:
            metadata_dict[_FIELD_PROJECT_NAME] = getattr(
                project, "name", self.jira_project
            )
            metadata_dict[_FIELD_PROJECT] = getattr(project, "key", self.jira_project)
        elif self.jira_project:
            metadata_dict[_FIELD_PROJECT] = self.jira_project
            metadata_dict[_FIELD_PROJECT_NAME] = self.jira_project

        # Populate JSM specific metadata
        if request_type:
            metadata_dict[FIELD_CUSTOMER_REQUEST_TYPE] = request_type
        if organizations:
            metadata_dict[FIELD_ORGANIZATIONS] = organizations
        if sla_info:
            metadata_dict[FIELD_SLA_STATUS] = [
                f"{name}: {status}" for name, status in sla_info.items()
            ]

        summary = getattr(issue.fields, "summary", issue.key)

        return Document(
            id=page_url,
            sections=[TextSection(link=page_url, text=ticket_content)],
            source=DocumentSource.JIRA_SERVICE_MANAGEMENT,
            semantic_identifier=f"[{self.jira_project}] {issue.key}: {summary}",
            title=f"[{issue.key}] {summary}",
            doc_updated_at=time_str_to_utc(issue.fields.updated)
            if hasattr(issue.fields, "updated") and issue.fields.updated
            else None,
            doc_created_at=time_str_to_utc(issue.fields.created)
            if hasattr(issue.fields, "created") and issue.fields.created
            else None,
            primary_owners=list(people) or None,
            metadata=metadata_dict,
            parent_hierarchy_raw_node_id=parent_hierarchy_raw_node_id,
        )
