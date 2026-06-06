from onyx.configs.constants import DocumentSource
from onyx.connectors.jira.connector import JiraConnector


class JiraServiceManagementConnector(JiraConnector):
    document_source = DocumentSource.JIRA_SERVICE_MANAGEMENT
