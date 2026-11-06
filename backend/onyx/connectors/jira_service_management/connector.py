from collections.abc import Iterator
from typing import Any

from typing_extensions import override

from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.jira.connector import JiraConnector, _perform_jql_search
from onyx.connectors.models import ConnectorMissingCredentialError

JSM_PROJECT_TYPE_KEYS = frozenset({"service_desk", "service_management"})
JSM_SPACE_TYPE_JQL = "spaceType = service_desk"


def _project_type_key(project: dict[str, Any]) -> str | None:
    """Read a Jira project type without accepting malformed API values."""
    project_type = project.get("projectTypeKey")
    return project_type if isinstance(project_type, str) else None


class JiraServiceManagementConnector(JiraConnector):
    """Index Jira service projects while preserving the distinct JSM source."""

    source = DocumentSource.JIRA_SERVICE_MANAGEMENT

    @override
    def _get_jql_query(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> str:
        """Keep incremental polling limited to the configured service scope."""
        base_jql = super()._get_jql_query(start, end)

        if self.jql_query:
            return base_jql.replace(
                f"({self.jql_query}) AND ",
                f"({self.jql_query}) AND {JSM_SPACE_TYPE_JQL} AND ",
                1,
            )

        if self.jira_project:
            return base_jql

        return f"{JSM_SPACE_TYPE_JQL} AND {base_jql}"

    @override
    def _search_all_issues(self, jql: str) -> Iterator[dict[str, Any]]:
        """Apply the service-project restriction to resolver and reindex queries."""
        return super()._search_all_issues(f"{JSM_SPACE_TYPE_JQL} AND ({jql})")

    @override
    def validate_connector_settings(self) -> None:
        """Validate credentials and reject non-service project configurations."""
        if self._source_operations is None:
            raise ConnectorMissingCredentialError("Jira Service Management")

        if self.jira_project and not self.jql_query:
            try:
                project = self.source_operations.get_project(
                    project_key=self.jira_project
                )
            except Exception as e:
                self._handle_jira_connector_settings_error(e)
                return

            project_type = _project_type_key(project)
            if project_type not in JSM_PROJECT_TYPE_KEYS:
                raise ConnectorValidationError(
                    f"Project '{self.jira_project}' is not a Jira Service Management project."
                )

            return

        try:
            next(
                iter(
                    _perform_jql_search(
                        source_operations=self.source_operations,
                        jql=(
                            f"({self.jql_query}) AND {JSM_SPACE_TYPE_JQL}"
                            if self.jql_query
                            else JSM_SPACE_TYPE_JQL
                        ),
                        start=0,
                        max_results=1,
                        all_issue_ids=[],
                    )
                ),
                None,
            )
        except Exception as e:
            self._handle_jira_connector_settings_error(e)
