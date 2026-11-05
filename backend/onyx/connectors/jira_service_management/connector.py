"""Jira Service Management connector that extends the standard Jira connector.

Jira Service Management (JSM) uses the same Jira API as regular Jira but is
specialized for IT service management, customer support, and operations. This
connector provides a dedicated DocumentSource for JSM projects while reusing
all the indexing, pagination, and permission sync logic from JiraConnector.
"""

from typing_extensions import override

from onyx.configs.app_configs import INDEX_BATCH_SIZE, JIRA_CONNECTOR_LABELS_TO_SKIP
from onyx.configs.constants import DocumentSource
from onyx.connectors.jira.connector import JiraConnector


class JiraServiceManagementConnector(JiraConnector):
    """Connector for Jira Service Management projects.

    JSM uses the same Jira REST API as regular Jira, so this connector inherits
    all functionality from JiraConnector. The key difference is the document_source
    property, which categorizes JSM documents separately for tracking and filtering.

    This approach avoids code duplication while providing a distinct connector type
    for service management projects.
    """

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
        """Initialize the JSM connector with the same parameters as Jira connector.

        Args:
            jira_base_url: Base URL of the Jira instance (e.g., https://company.atlassian.net)
            project_key: Optional project key to filter by (e.g., "SUPPORT", "ITHELP")
            comment_email_blacklist: Email addresses whose comments should be excluded
            batch_size: Number of issues to fetch per API call
            labels_to_skip: Issue labels to exclude from indexing
            jql_query: Optional JQL query to further filter issues (takes precedence over project_key)
            scoped_token: Whether to use a scoped API token (Cloud Gateway)
        """
        super().__init__(
            jira_base_url=jira_base_url,
            project_key=project_key,
            comment_email_blacklist=comment_email_blacklist,
            batch_size=batch_size,
            labels_to_skip=labels_to_skip,
            jql_query=jql_query,
            scoped_token=scoped_token,
        )

    @override
    @property
    def document_source(self) -> DocumentSource:
        """Returns JIRA_SERVICE_MANAGEMENT to categorize JSM documents separately."""
        return DocumentSource.JIRA_SERVICE_MANAGEMENT
