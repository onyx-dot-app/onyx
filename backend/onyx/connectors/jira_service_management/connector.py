from datetime import datetime
from datetime import timezone

from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.jira.connector import JiraConnector


class JiraServiceManagementConnector(JiraConnector):
    """Dedicated connector for Jira Service Management lanes.

    Keeps Jira connector behavior, but scopes default search to JSM projects
    when a custom JQL query is not provided.
    """

    @property
    def document_source(self) -> DocumentSource:
        return DocumentSource.JIRA_SERVICE_MANAGEMENT

    def _get_jql_query(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> str:
        start_date_str = datetime.fromtimestamp(start, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M"
        )
        end_date_str = datetime.fromtimestamp(end, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M"
        )
        time_jql = f"updated >= '{start_date_str}' AND updated <= '{end_date_str}'"

        if self.jql_query:
            return f"({self.jql_query}) AND {time_jql}"

        if self.jira_project:
            return f'project = "{self.jira_project}" AND projectType = service_desk AND {time_jql}'

        return f"projectType = service_desk AND {time_jql}"
