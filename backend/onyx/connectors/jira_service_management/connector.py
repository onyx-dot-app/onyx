from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.jira.connector import JiraConnector

JSM_PROJECT_TYPE_KEY = "service_desk"
JSM_PROJECT_TYPE_JQL_FILTER = f'projectType = "{JSM_PROJECT_TYPE_KEY}"'


class JiraServiceManagementConnector(JiraConnector):
    """Connector for Jira Service Management (service desk) projects.

    Reuses ``JiraConnector``'s indexing, checkpointing, hierarchy, and
    permission-sync pipeline while scoping JQL queries to JSM projects
    (``projectType = "service_desk"``) unless a custom ``jql_query`` is set.
    """

    source: DocumentSource = DocumentSource.JIRA_SERVICE_MANAGEMENT

    def _extra_jql_filter(self) -> str | None:
        if self.jql_query:
            return None
        return JSM_PROJECT_TYPE_JQL_FILTER

    def validate_connector_settings(self) -> None:
        if self._source_operations is None:
            raise ConnectorValidationError("Credentials must be loaded first")

        if self.jql_query:
            super().validate_connector_settings()
            return

        if self.jira_project:
            try:
                project = self.source_operations.get_project(
                    project_key=self.jira_project
                )
            except Exception as e:
                self._handle_jira_connector_settings_error(e)

            project_type = (
                project.get("projectTypeKey")
                if isinstance(project, dict)
                else getattr(project, "projectTypeKey", None)
            )
            if (
                isinstance(project_type, str)
                and project_type != JSM_PROJECT_TYPE_KEY
            ):
                raise ConnectorValidationError(
                    f"Project '{self.jira_project}' has projectTypeKey '{project_type}', "
                    f"expected '{JSM_PROJECT_TYPE_KEY}' for Jira Service Management."
                )
            return

        super().validate_connector_settings()
