"""Jira Service Management (JSM) connector.

JSM projects are Jira projects under the hood and are served by the same
REST API and JQL surface, so this connector is a thin specialization of
``JiraConnector`` that emits documents under
``DocumentSource.JIRA_SERVICE_MANAGEMENT``.
"""

from onyx.configs.constants import DocumentSource
from onyx.connectors.jira.connector import JiraConnector


class JiraServiceManagementConnector(JiraConnector):
    source: DocumentSource = DocumentSource.JIRA_SERVICE_MANAGEMENT
