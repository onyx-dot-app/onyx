from typing import Any

from typing_extensions import override

from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.jira.connector import _perform_jql_search
from onyx.connectors.jira.connector import JiraConnector
from onyx.connectors.models import ConnectorMissingCredentialError

JSM_PROJECT_TYPE_KEYS = frozenset({"service_desk", "service_management"})
JSM_SPACE_TYPE_JQL = "spaceType = service_desk"


def _project_type_key(project: Any) -> str | None:
    project_type = getattr(project, "projectTypeKey", None)
    if isinstance(project_type, str):
        return project_type

    raw = getattr(project, "raw", None)
    if isinstance(raw, dict):
        raw_type = raw.get("projectTypeKey")
        if isinstance(raw_type, str):
            return raw_type

    return None


class JiraServiceManagementConnector(JiraConnector):
    source = DocumentSource.JIRA_SERVICE_MANAGEMENT

    @override
    def _get_jql_query(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> str:
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
    def validate_connector_settings(self) -> None:
        if self._jira_client is None:
            raise ConnectorMissingCredentialError("Jira Service Management")

        if self.jira_project and not self.jql_query:
            try:
                project = self.jira_client.project(self.jira_project)
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
                        jira_client=self.jira_client,
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
