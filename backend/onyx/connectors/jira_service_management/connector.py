"""Jira Service Management (JSM) connector.

A JSM project is a Jira project whose project type is ``service_desk``: the
issues REST API and permission model are the same, so the JSM connector
inherits the battle-tested Jira ingestion engine and only differs where JSM
does:

* It registers as its own document source (``jira_service_management``) so
  teams can run a connector scoped to their help desk next to a normal Jira
  connector, with independent permission and indexing settings.
* ``validate_connector_settings`` requires the scoped project to literally be
  a Service Management project, so a click typo surfaces in the setup form
  instead of silently indexing an unrelated project.
* Credentials are shared with the Jira/Confluence atlassian family.

Permission syncing, checkpointing, hierarchy, and the slim flows are inherited
unchanged; JSM request/customer organizations resolve through the same Jira
roles and groups as Jira issues.
"""

from typing import Any

from onyx.configs.app_configs import INDEX_BATCH_SIZE, JIRA_CONNECTOR_LABELS_TO_SKIP
from onyx.configs.constants import DocumentSource
from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.jira.connector import JiraConnector
from onyx.connectors.jira.source_operations import JiraSourceOperations
from onyx.connectors.jira_service_management.access import (
    require_service_management_project,
)
from onyx.connectors.models import ConnectorMissingCredentialError


class JiraServiceManagementConnector(JiraConnector):
    """Indexes the issues of a Jira Service Management project."""

    def __init__(
        self,
        jira_base_url: str,
        project_key: str | None = None,
        comment_email_blacklist: list[str] | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
        labels_to_skip: list[str] = JIRA_CONNECTOR_LABELS_TO_SKIP,
        jql_query: str | None = None,
        scoped_token: bool = False,
    ) -> None:
        super().__init__(
            jira_base_url=jira_base_url,
            project_key=project_key,
            comment_email_blacklist=comment_email_blacklist,
            batch_size=batch_size,
            labels_to_skip=labels_to_skip,
            jql_query=jql_query,
            scoped_token=scoped_token,
        )

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        # Identical to the Jira connector, but tagged with the JSM source so
        # audit/credential context and permission-sync bookkeeping stay
        # distinct from a coexisting Jira connector.
        self._source_operations = JiraSourceOperations(
            credentials_provider=OnyxStaticCredentialsProvider(
                None, DocumentSource.JIRA_SERVICE_MANAGEMENT.value, credentials
            ),
            connector_specific_config={
                "jira_base_url": self.jira_base,
                "scoped_token": self.scoped_token,
            },
        )
        return None

    def validate_connector_settings(self) -> None:
        if self._source_operations is None:
            raise ConnectorMissingCredentialError("Jira Service Management")

        # The one JSM-specific gate: only Service Management projects, and
        # only when the scope is a project (a custom JQL can span projects,
        # so no project type applies). The type check doubles as the Jira
        # "project exists" check, so a project scope fetches the project once.
        if self.jira_project and not self.jql_query:
            require_service_management_project(
                source_operations=self.source_operations,
                project_key=self.jira_project,
            )
            return

        # JQL syntax / API access, the Jira way.
        super().validate_connector_settings()
