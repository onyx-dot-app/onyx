"""Jira Service Management connector.

Atlassian Jira and Jira Service Management share the same REST API endpoints —
the difference is the project type ('software' vs 'service_desk') and the set
of customfields exposed on issues. The connector therefore reuses the existing
Jira connector implementation and only overrides the DocumentSource so JSM
tickets are tagged distinctly in the index.

JSM-specific fields (request type, SLA, organization, customer reporter) are
already surfaced by the parent connector via `best_effort_get_field_from_issue`
and the comment / metadata flow — no extra parsing is required for the base
case. JSM-specific custom-field handling can be layered on later by overriding
`process_jira_issue`-equivalent hooks if needed.
"""

from onyx.configs.constants import DocumentSource
from onyx.connectors.jira.connector import JiraConnector


class JiraServiceManagementConnector(JiraConnector):
    """Thin subclass that tags produced documents as JIRA_SERVICE_MANAGEMENT.

    All ingestion behaviour (JQL, checkpointing, slim sync, permissions) is
    inherited from JiraConnector. Operators configure this connector with the
    same Atlassian base URL + API token; pointing it at a service-desk project
    key is the recommended scoping mechanism.
    """

    _source: DocumentSource = DocumentSource.JIRA_SERVICE_MANAGEMENT
