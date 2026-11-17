"""Jira Service Management connector.

JSM tickets are Jira issues in a service desk project, so this connector
reuses the Jira connector's search, checkpointing, slim listing and permission
sync, scoped to one configured project, and adds the Service Desk REST API
on top: request details (type, service desk, organization) and SLAs become
metadata, and comments are filtered by their customer-visible flag so
agent-only (internal) notes stay out of the index unless configured
otherwise.
"""

import os
from typing import Any, ClassVar

from onyx.configs.app_configs import (
    INDEX_BATCH_SIZE,
    JIRA_CONNECTOR_LABELS_TO_SKIP,
)
from onyx.configs.constants import DocumentSource
from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.jira.connector import (
    JiraConnector,
    JiraIssue,
    _issue_key,
    process_jira_issue,
)
from onyx.connectors.jira.source_operations import (
    JiraApiError,
    JiraSourceOperations,
)
from onyx.connectors.jira.utils import get_comment_strs, rich_text
from onyx.connectors.jira_service_management.models import JsmComment, JsmSla
from onyx.connectors.jira_service_management.source_operations import (
    JiraServiceManagementSourceOperations,
)
from onyx.connectors.models import (
    ConnectorMissingCredentialError,
    Document,
    TextSection,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

# The servicedesk API answers 404 when the site has no JSM app; the project
# itself was already validated through the Jira API.
_SERVICEDESK_MISSING_STATUS = 404


class JiraServiceManagementConnector(JiraConnector):
    document_source: ClassVar[DocumentSource] = DocumentSource.JIRA_SERVICE_MANAGEMENT

    def __init__(
        self,
        jira_base_url: str,
        project_key: str,
        scoped_token: bool = False,
        include_internal_comments: bool = False,
        comment_email_blacklist: list[str] | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
        # if a ticket has one of the labels specified in this list, we will
        # just skip it. This is generally used to avoid indexing extra
        # sensitive tickets.
        labels_to_skip: list[str] = JIRA_CONNECTOR_LABELS_TO_SKIP,
    ) -> None:
        super().__init__(
            jira_base_url=jira_base_url,
            project_key=project_key,
            comment_email_blacklist=comment_email_blacklist,
            batch_size=batch_size,
            labels_to_skip=labels_to_skip,
            jql_query=None,
            scoped_token=scoped_token,
        )
        self.include_internal_comments = include_internal_comments
        self._jsm_operations: JiraServiceManagementSourceOperations | None = None

    @property
    def jsm_operations(self) -> JiraServiceManagementSourceOperations:
        if self._jsm_operations is None:
            raise ConnectorMissingCredentialError("Jira Service Management")
        return self._jsm_operations

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        provider = OnyxStaticCredentialsProvider(
            None, DocumentSource.JIRA_SERVICE_MANAGEMENT.value, credentials
        )
        config = {
            "jira_base_url": self.jira_base,
            "scoped_token": self.scoped_token,
        }
        # Issue search goes through the Jira gateway; the servicedesk calls
        # through this source's own gateway. Both share one provider.
        self._source_operations = JiraSourceOperations(
            credentials_provider=provider,
            connector_specific_config=config,
        )
        self._jsm_operations = JiraServiceManagementSourceOperations(
            credentials_provider=provider,
            connector_specific_config=config,
        )
        return None

    def _service_desk_comment_strs(self, issue_key: str, issue: JiraIssue) -> list[str]:
        """The comment strings of a request, filtered by visibility.

        Falls back to the comments embedded in the Jira issue when the
        servicedesk API does not know the request (e.g. the site has no JSM
        app), where no visibility flag exists.
        """
        try:
            comments: list[JsmComment] = self.jsm_operations.get_request_comments(
                issue_key=issue_key
            )
        except JiraApiError as e:
            if not self.include_internal_comments:
                logger.warning(
                    "Could not fetch service desk comments for %s (%s); omitting "
                    "comments because include_internal_comments is disabled.",
                    issue_key,
                    e,
                )
                return []
            logger.warning(
                "Could not fetch service desk comments for %s (%s); falling back "
                "to the issue's embedded comments.",
                issue_key,
                e,
            )
            return get_comment_strs(
                issue=issue, comment_email_blacklist=self.comment_email_blacklist
            )

        comment_strs: list[str] = []
        for comment in comments:
            if not self.include_internal_comments and not comment.public:
                continue
            if comment.author_email in self.comment_email_blacklist:
                continue
            text: str = rich_text(comment.body)
            if text:
                comment_strs.append(text)
        return comment_strs

    def _sla_lines(self, issue_key: str) -> list[str]:
        try:
            slas: list[JsmSla] = self.jsm_operations.get_request_slas(
                issue_key=issue_key
            )
        except JiraApiError as e:
            logger.warning("Could not fetch SLAs for %s: %s", issue_key, e)
            return []
        lines: list[str] = []
        for sla in slas:
            if not sla.name:
                continue
            if sla.breached is None:
                state = "unknown"
            else:
                state = "breached" if sla.breached else "within goal"
            line = f"SLA {sla.name}: {state}"
            if sla.goal:
                line += f" (goal {sla.goal})"
            lines.append(line)
        return lines

    def _enrich_document(self, document: Document, issue_key: str) -> None:
        """Adds the service desk request details and SLAs of a ticket to its
        metadata, and the SLAs as an extra searchable section. A failure of
        the servicedesk API never drops the ticket."""
        try:
            request = self.jsm_operations.get_request(issue_key=issue_key)
        except JiraApiError as e:
            logger.warning("Could not fetch service desk request %s: %s", issue_key, e)
            request = None
        if request is not None:
            if request.request_type_name:
                document.metadata["request_type"] = request.request_type_name
            if request.service_desk_name:
                document.metadata["service_desk"] = request.service_desk_name
            if request.status:
                document.metadata["request_status"] = request.status
            if request.organizations:
                document.metadata["organizations"] = request.organizations

        sla_lines = self._sla_lines(issue_key)
        if sla_lines:
            document.metadata["sla"] = sla_lines
            document.sections.append(
                TextSection(link=document.id, text="\n".join(sla_lines))
            )

    def _process_issue(
        self,
        issue: JiraIssue,
        parent_hierarchy_raw_node_id: str | None = None,
    ) -> Document | None:
        issue_key = _issue_key(issue)
        document = process_jira_issue(
            jira_base_url=self.jira_base,
            issue=issue,
            comment_email_blacklist=self.comment_email_blacklist,
            labels_to_skip=self.labels_to_skip,
            parent_hierarchy_raw_node_id=parent_hierarchy_raw_node_id,
            source=self.document_source,
            comments=self._service_desk_comment_strs(issue_key, issue),
        )
        if document is None:
            return None
        self._enrich_document(document, issue_key)
        return document

    def validate_connector_settings(self) -> None:
        # Validates the credentials and that the project exists.
        super().validate_connector_settings()
        if not self.jira_project:
            return
        try:
            desks = self.jsm_operations.list_service_desks()
        except JiraApiError as e:
            if e.status_code == _SERVICEDESK_MISSING_STATUS:
                logger.warning(
                    "The servicedesk API is not available on %s (HTTP 404); "
                    "skipping the service desk check. The project itself was "
                    "validated through the Jira API.",
                    self.jira_base,
                )
                return
            self._handle_jira_connector_settings_error(e)
            return
        desk_keys = {desk.project_key.upper() for desk in desks}
        if self.jira_project.upper() not in desk_keys:
            raise ConnectorValidationError(
                f"Project '{self.jira_project}' is not a Jira Service Management "
                "project: no service desk serves it. Service desk projects: "
                f"{', '.join(sorted(desk_keys)) or 'none'}."
            )


if __name__ == "__main__":
    import time

    connector = JiraServiceManagementConnector(
        jira_base_url=os.environ["JIRA_BASE_URL"],
        project_key=os.environ["JSM_PROJECT_KEY"],
    )
    connector.load_credentials(
        {
            "jira_user_email": os.environ["JIRA_USER_EMAIL"],
            "jira_api_token": os.environ["JIRA_API_TOKEN"],
        }
    )

    current = time.time()
    one_day_ago = current - 24 * 60 * 60
    for doc in connector.load_from_checkpoint(
        one_day_ago, current, connector.build_dummy_checkpoint()
    ):
        print(doc)
