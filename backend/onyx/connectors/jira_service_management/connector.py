from onyx.configs.constants import DocumentSource
from onyx.connectors.jira.connector import JiraConnector


class JiraServiceManagementConnector(JiraConnector):
    """
    A thin wrapper around JiraConnector that uses DocumentSource.JIRA_SERVICE_MANAGEMENT.
    Jira Service Management uses the exact same API and JQL surface as regular Jira.
    """

    source: DocumentSource = DocumentSource.JIRA_SERVICE_MANAGEMENT
