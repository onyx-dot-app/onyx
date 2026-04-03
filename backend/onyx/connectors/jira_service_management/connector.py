from typing_extensions import override

from onyx.configs.constants import DocumentSource
from onyx.connectors.onyx_jira.connector import JiraConnector


_JSM_ISSUE_TYPE_FILTER = 'issuetype in ("Service Request", "Incident", "Problem", "Change", "Service Task")'


class JiraServiceManagementConnector(JiraConnector):
    @property
    @override
    def source(self) -> DocumentSource:
        return DocumentSource.JIRA_SERVICE_MANAGEMENT

    @property
    @override
    def source_display_name(self) -> str:
        return "Jira Service Management"

    @property
    @override
    def jql_issue_type_filter(self) -> str:
        return _JSM_ISSUE_TYPE_FILTER
