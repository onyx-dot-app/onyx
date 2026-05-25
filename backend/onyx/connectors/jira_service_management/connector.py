"""Jira Service Management (JSM) connector.

JSM projects are Jira projects under the hood and share the same REST API + JQL
surface. This connector reuses the existing Jira connector implementation, but
emits documents under a dedicated `DocumentSource` so JSM tickets can be
configured and displayed separately in Onyx.
"""

from onyx.configs.constants import DocumentSource
from onyx.connectors.jira.connector import JiraConnector


class JiraServiceManagementConnector(JiraConnector):
    source: DocumentSource = DocumentSource.JIRA_SERVICE_MANAGEMENT
