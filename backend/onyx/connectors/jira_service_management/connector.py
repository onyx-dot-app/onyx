from onyx.configs.app_configs import (
    INDEX_BATCH_SIZE,
    JIRA_CONNECTOR_LABELS_TO_SKIP,
)
from onyx.configs.constants import DocumentSource
from onyx.connectors.jira.connector import JiraConnector

# JQL filter that matches only Jira Service Management (service-desk) projects
JSM_PROJECT_TYPE_JQL = "projectType = service_desk"


class JiraServiceManagementConnector(JiraConnector):
    """Connector for Jira Service Management (JSM).

    Reuses the Jira connector; when no project key or custom JQL is given,
    indexing is scoped to service-desk projects so plain Jira Software
    projects are excluded.
    """

    document_source = DocumentSource.JIRA_SERVICE_MANAGEMENT

    def __init__(
        self,
        jira_base_url: str,
        project_key: str | None = None,
        comment_email_blacklist: list[str] | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
        labels_to_skip: list[str] = JIRA_CONNECTOR_LABELS_TO_SKIP,
        jql_query: str | None = None,
        scoped_token: bool = False,
    ) -> None:
        # Default to service-desk projects if no explicit scope was provided
        if not project_key and not jql_query:
            jql_query = JSM_PROJECT_TYPE_JQL

        super().__init__(
            jira_base_url=jira_base_url,
            project_key=project_key,
            comment_email_blacklist=comment_email_blacklist,
            batch_size=batch_size,
            labels_to_skip=labels_to_skip,
            jql_query=jql_query,
            scoped_token=scoped_token,
        )
