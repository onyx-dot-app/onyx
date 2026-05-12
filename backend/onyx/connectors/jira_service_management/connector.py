"""
Jira Service Management (JSM) Connector.

This is a thin subclass of the existing Jira connector. JSM uses the same
underlying Jira APIs and authentication, so the only meaningful differences
are the DocumentSource tag and the connector's constructor parameter name
(``jira_service_management_base_url`` instead of ``jira_base_url``).
"""

from typing_extensions import override

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.app_configs import JIRA_CONNECTOR_LABELS_TO_SKIP
from onyx.configs.constants import DocumentSource
from onyx.connectors.jira.connector import JiraConnector


class JiraServiceManagementConnector(JiraConnector):
    """Connector for Jira Service Management projects.

    Inherits all indexing, checkpointing, and permission-sync logic from
    :class:`JiraConnector`.  The only overrides are:

    * ``document_source`` — returns ``DocumentSource.JIRA_SERVICE_MANAGEMENT``
      so that indexed documents are tagged correctly.
    * ``__init__`` — accepts ``jira_service_management_base_url`` and forwards
      it as ``jira_base_url`` to the parent class.
    """

    def __init__(
        self,
        jira_service_management_base_url: str,
        project_key: str | None = None,
        comment_email_blacklist: list[str] | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
        labels_to_skip: list[str] = JIRA_CONNECTOR_LABELS_TO_SKIP,
        jql_query: str | None = None,
        scoped_token: bool = False,
    ) -> None:
        super().__init__(
            jira_base_url=jira_service_management_base_url,
            project_key=project_key,
            comment_email_blacklist=comment_email_blacklist,
            batch_size=batch_size,
            labels_to_skip=labels_to_skip,
            jql_query=jql_query,
            scoped_token=scoped_token,
        )

    @property
    @override
    def document_source(self) -> DocumentSource:
        return DocumentSource.JIRA_SERVICE_MANAGEMENT
