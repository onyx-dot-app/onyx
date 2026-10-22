import logging
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple

from danswer.connectors.jira.connector import JiraConnector
from danswer.connectors.jira.connector import JiraConfig
from danswer.connectors.jira.connector import JiraIssue
from danswer.connectors.jira.connector import JiraIssueFields
from danswer.connectors.jira.connector import JiraIssueType
from danswer.connectors.jira.connector import JiraProject
from danswer.connectors.jira.connector import JiraUser
from danswer.connectors.jira.connector import JiraWebhook
from danswer.connectors.jira.connector import JQL_ISSUE_TYPE_FILTER
from danswer.connectors.jira.utils import get_jira_client
from danswer.connectors.jira_service_management.constants import JSM_DEFAULT_JQL_FILTER
from danswer.connectors.jira_service_management.models import JiraServiceManagementConfig
from danswer.connectors.models import Document
from danswer.connectors.models import Section
from danswer.connectors.models import SmallFileInfo
from danswer.utils.logger import setup_logger

logger = setup_logger()


class JiraServiceManagementConnector(JiraConnector):
    def __init__(
        self,
        connector_config: JiraServiceManagementConfig,
        credential_id: Optional[int] = None,
        is_cancelling: Optional[callable] = None,
    ):
        super().__init__(
            connector_config=JiraConfig(
                jira_url=connector_config.jira_url,
                jira_username=connector_config.jira_username,
                jira_api_token=connector_config.jira_api_token,
                project_keys=connector_config.project_keys,
                include_attachments=connector_config.include_attachments,
                include_comments=connector_config.include_comments,
                include_subtasks=connector_config.include_subtasks,
                custom_jql_query=connector_config.custom_jql_query,
            ),
            credential_id=credential_id,
            is_cancelling=is_cancelling,
        )
        self.connector_config = connector_config
        self.jira_client = get_jira_client(
            connector_config.jira_url,
            connector_config.jira_username,
            connector_config.jira_api_token,
        )

    def _get_jql_query(self, project_key: str) -> str:
        """Constructs the JQL query for fetching JSM tickets."""
        base_jql = f"project = '{project_key}'"

        # Apply JSM specific filter if no custom JQL is provided
        if not self.connector_config.custom_jql_query:
            base_jql += f" AND {JSM_DEFAULT_JQL_FILTER}"
            if not self.connector_config.include_subtasks:
                base_jql += f" AND {JQL_ISSUE_TYPE_FILTER}"
        else:
            # If custom JQL is provided, it takes precedence
            base_jql = self.connector_config.custom_jql_query

        return base_jql

    def _get_all_jira_issues_for_project(
        self, project_key: str, current_project_issues: List[str]
    ) -> Tuple[List[JiraIssue], List[str]]:
        """Fetches all issues for a given project key, applying JSM specific filters."""
        jql_query = self._get_jql_query(project_key)
        logger.info(f"Fetching JSM issues for project '{project_key}' with JQL: {jql_query}")

        all_issues: List[JiraIssue] = []
        start_at = 0
        max_results = 50  # Jira's default max_results per page

        while True:
            if self.is_cancelling and self.is_cancelling():
                logger.warning("Jira Service Management connector cancelled.")
                break

            try:
                issues_page = self.jira_client.search_issues(
                    jql_query,
                    startAt=start_at,
                    maxResults=max_results,
                    fields="*all",  # Fetch all fields to ensure we get JSM specific ones
                )
            except Exception as e:
                logger.error(f"Failed to fetch JSM issues for project {project_key}: {e}")
                break

            if not issues_page:
                break

            for issue in issues_page:
                # Convert raw Jira issue to our Pydantic model
                issue_fields = JiraIssueFields(
                    summary=issue.fields.summary,
                    description=getattr(issue.fields, "description", None),
                    status=issue.fields.status.name,
                    reporter=JiraUser(
                        name=issue.fields.reporter.displayName,
                        emailAddress=getattr(issue.fields.reporter, "emailAddress", None),
                    )
                    if issue.fields.reporter
                    else None,
                    assignee=JiraUser(
                        name=issue.fields.assignee.displayName,
                        emailAddress=getattr(issue.fields.assignee, "emailAddress", None),
                    )
                    if issue.fields.assignee
                    else None,
                    created=issue.fields.created,
                    updated=issue.fields.updated,
                    issueType=JiraIssueType(name=issue.fields.issuetype.name),
                    project=JiraProject(key=issue.fields.project.key, name=issue.fields.project.name),
                    # Add any other relevant fields, potentially custom fields
                    # For JSM, we might want to capture 'Request Type' or 'Service Desk' fields
                    # These are often custom fields, so we'd need to dynamically look them up
                    # For now, we rely on "*all" and will process them in _jira_issue_to_document
                )
                jira_issue = JiraIssue(
                    id=issue.id,
                    key=issue.key,
                    url=f"{self.connector_config.jira_url}/browse/{issue.key}",
                    fields=issue_fields,
                    raw_issue=issue.raw,  # Store raw data for flexible processing
                )
                all_issues.append(jira_issue)

            if len(issues_page) < max_results:
                break
            start_at += max_results

        return all_issues, [issue.key for issue in all_issues]

    def _jira_issue_to_document(self, jira_issue: JiraIssue) -> Document:
        """Converts a JiraIssue object to a Danswer Document, with JSM specific enhancements."""
        document = super()._jira_issue_to_document(jira_issue)

        # Enhance metadata with JSM specific fields if available in raw_issue
        if jira_issue.raw_issue:
            raw_fields = jira_issue.raw_issue.get("fields", {})
            # Example: Try to extract 'Request Type' which is often a custom field in JSM
            # This requires knowing the custom field ID or name.
            # For a robust solution, we'd need a way to configure these custom fields.
            # For now, we can try common patterns or rely on the user to specify.
            # A common pattern for Request Type is 'customfield_XXXXX'
            # We can iterate through custom fields if we know their names or IDs.
            for field_name, field_value in raw_fields.items():
                if "request type" in field_name.lower() or "servicedesk" in field_name.lower():
                    if isinstance(field_value, dict) and "value" in field_value:
                        document.metadata[field_name] = field_value["value"]
                    elif isinstance(field_value, str):
                        document.metadata[field_name] = field_value
                    # Add other JSM specific fields as needed
                    # e.g., 'Customer Request Type', 'Service Desk Name', 'Organization'

            # Add the project name to the metadata for better filtering/display
            if jira_issue.fields.project:
                document.metadata["project_name"] = jira_issue.fields.project.name
                document.metadata["project_key"] = jira_issue.fields.project.key

            # Add issue type to metadata
            if jira_issue.fields.issueType:
                document.metadata["issue_type"] = jira_issue.fields.issueType.name

        # Ensure the document has a title and content
        if not document.title:
            document.title = jira_issue.fields.summary or f"JSM Ticket {jira_issue.key}"
        if not document.sections:
            content = jira_issue.fields.description or ""
            if jira_issue.fields.summary:
                content = f"{jira_issue.fields.summary}\n\n{content}"
            document.sections = [Section(text=content, link=document.link)]

        return document

    def get_documents(self, last_run_t: Optional[int] = None) -> List[Document]:
        """
        Fetches all JSM tickets from the configured projects and converts them into Danswer Documents.
        """
        all_documents: List[Document] = []
        for project_key in self.connector_config.project_keys:
            logger.info(f"Starting JSM sync for project: {project_key}")
            # For JSM, we typically want to re-fetch all relevant tickets,
            # or at least those updated since last_run_t.
            # The base JiraConnector handles last_run_t in _get_all_jira_issues_for_project
            # by modifying the JQL. We'll ensure our _get_jql_query integrates this.
            # For now, we'll rely on the base class's `get_documents` which calls
            # `_get_all_jira_issues_for_project` with the appropriate JQL.
            # We just need to ensure our `_get_jql_query` is used.

            # The base class's `get_documents` method already orchestrates fetching
            # issues and converting them. We just need to ensure our overridden
            # `_get_jql_query` and `_jira_issue_to_document` are used.
            # The `_get_all_jira_issues_for_project` method is also overridden
            # to use our JSM-specific JQL.

            # We can call the parent's get_documents, which will in turn call our
            # overridden methods.
            project_documents = super().get_documents(last_run_t=last_run_t)
            all_documents.extend(project_documents)

        return all_documents

    def get_or_create_webhook(self, connector_id: int, api_key: str) -> Optional[JiraWebhook]:
        """JSM connector does not support webhooks directly for now."""
        logger.info("Jira Service Management connector does not support webhooks.")
        return None

    def delete_webhook(self, webhook_id: str) -> None:
        """JSM connector does not support webhooks directly for now."""
        logger.info("Jira Service Management connector does not support webhooks.")
        pass

    def get_issue_by_key(self, issue_key: str) -> Optional[JiraIssue]:
        """Fetches a single JSM issue by its key."""
        try:
            issue = self.jira_client.issue(issue_key, fields="*all")
            issue_fields = JiraIssueFields(
                summary=issue.fields.summary,
                description=getattr(issue.fields, "description", None),
                status=issue.fields.status.name,
                reporter=JiraUser(
                    name=issue.fields.reporter.displayName,
                    emailAddress=getattr(issue.fields.reporter, "emailAddress", None),
                )
                if issue.fields.reporter
                else None,
                assignee=JiraUser(
                    name=issue.fields.assignee.displayName,
                    emailAddress=getattr(issue.fields.assignee, "emailAddress", None),
                )
                if issue.fields.assignee
                else None,
                created=issue.fields.created,
                updated=issue.fields.updated,
                issueType=JiraIssueType(name=issue.fields.issuetype.name),
                project=JiraProject(key=issue.fields.project.key, name=issue.fields.project.name),
            )
            return JiraIssue(
                id=issue.id,
                key=issue.key,
                url=f"{self.connector_config.jira_url}/browse/{issue.key}",
                fields=issue_fields,
                raw_issue=issue.raw,
            )
        except Exception as e:
            logger.error(f"Failed to fetch JSM issue {issue_key}: {e}")
            return None

    def get_issue_comments(self, issue_key: str) -> List[Dict[str, Any]]:
        """Fetches comments for a JSM issue."""
        return super().get_issue_comments(issue_key)

    def get_issue_attachments(self, issue_key: str) -> List[SmallFileInfo]:
        """Fetches attachments for a JSM issue."""
        return super().get_issue_attachments(issue_key)
