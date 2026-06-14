from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.app_configs import JIRA_CONNECTOR_LABELS_TO_SKIP
from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.jira.connector import JiraConnector


class JiraServiceManagementConnector(JiraConnector):
    """Index Jira Service Management tickets from a single Jira project."""

    def __init__(
        self,
        jira_base_url: str,
        project_key: str,
        comment_email_blacklist: list[str] | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
        labels_to_skip: list[str] = JIRA_CONNECTOR_LABELS_TO_SKIP,
        jql_query: str | None = None,
        scoped_token: bool = False,
    ) -> None:
        if not project_key:
            raise ConnectorValidationError(
                "Jira Service Management connector requires a project key."
            )

        project_jql = f'project = "{project_key}"'
        effective_jql_query = f"{project_jql} AND ({jql_query})" if jql_query else None

        super().__init__(
            jira_base_url=jira_base_url,
            project_key=project_key,
            comment_email_blacklist=comment_email_blacklist,
            batch_size=batch_size,
            labels_to_skip=labels_to_skip,
            jql_query=effective_jql_query,
            scoped_token=scoped_token,
            document_source=DocumentSource.JIRA_SERVICE_MANAGEMENT,
        )
