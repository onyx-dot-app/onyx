"""Jira Service Management (JSM) connector.

Indexes service desk tickets (requests, incidents, problems, changes) from
Jira Service Management projects.  Reuses all pagination, checkpointing,
and permission-sync logic from JiraConnector; the only additions are:

* DocumentSource.JIRA_SERVICE_MANAGEMENT is stamped on every yielded
  document so that JSM content is searchable as a distinct source type.
* When no project_key or custom jql_query is provided the connector
  automatically restricts the JQL to ``project type = "service_management"``
  so that only service desk projects are indexed.
* validate_connector_settings warns when a caller supplies a project_key
  that belongs to a non-service-management project.
"""

from __future__ import annotations

from collections.abc import Generator
from typing import TypeVar

from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.interfaces import CheckpointOutput
from onyx.connectors.interfaces import GenerateSlimDocumentOutput
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.jira.connector import JiraConnector
from onyx.connectors.jira.connector import JiraConnectorCheckpoint
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import Document
from onyx.connectors.models import HierarchyNode
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger

logger = setup_logger()

_CT = TypeVar("_CT")

_JSM_PROJECT_TYPE = "service_management"


def _stamp_source(
    gen: CheckpointOutput[_CT],
    source: DocumentSource,
) -> Generator[Document | HierarchyNode | ConnectorFailure, None, _CT]:
    """Wrap a CheckpointOutput generator, overwriting Document.source."""
    try:
        while True:
            item = next(gen)
            if isinstance(item, Document):
                item.source = source
            yield item
    except StopIteration as exc:
        return exc.value  # type: ignore[return-value]


class JiraServiceManagementConnector(JiraConnector):
    """Connector for Jira Service Management projects.

    Accepts the same constructor arguments as JiraConnector.
    The project_key parameter should be the key of a JSM service-desk
    project (e.g. "HELP" or "IT").  When omitted, every service
    management project accessible with the provided credentials is indexed.
    """

    def _get_jql_query(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
    ) -> str:
        base_jql = super()._get_jql_query(start, end)

        # If the caller already scoped the query (custom JQL or specific
        # project key), trust them and skip the extra project-type filter.
        if self.jql_query or self.jira_project:
            return base_jql

        # No scope specified: automatically restrict to JSM projects.
        return f'({base_jql}) AND project type = "{_JSM_PROJECT_TYPE}"'

    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: JiraConnectorCheckpoint,
    ) -> CheckpointOutput[JiraConnectorCheckpoint]:
        return _stamp_source(
            super().load_from_checkpoint(start, end, checkpoint),
            DocumentSource.JIRA_SERVICE_MANAGEMENT,
        )

    def load_from_checkpoint_with_perm_sync(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: JiraConnectorCheckpoint,
    ) -> CheckpointOutput[JiraConnectorCheckpoint]:
        return _stamp_source(
            super().load_from_checkpoint_with_perm_sync(start, end, checkpoint),
            DocumentSource.JIRA_SERVICE_MANAGEMENT,
        )

    def retrieve_all_slim_docs_perm_sync(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        # SlimDocuments don't carry a source field, so pass through unchanged.
        yield from super().retrieve_all_slim_docs_perm_sync(start, end, callback)

    def validate_connector_settings(self) -> None:
        # When a project key is given (without custom JQL) we validate existence
        # and check the project type in a single project() call, avoiding the
        # redundant call that super() would otherwise make.
        if self.jira_project and not self.jql_query:
            if self._jira_client is None:
                from onyx.connectors.models import ConnectorMissingCredentialError

                raise ConnectorMissingCredentialError("Jira")
            try:
                project = self.jira_client.project(self.jira_project)
                project_type = getattr(project, "projectTypeKey", None)
                if project_type and project_type != _JSM_PROJECT_TYPE:
                    raise ConnectorValidationError(
                        f"Project '{self.jira_project}' has project type "
                        f"'{project_type}', not '{_JSM_PROJECT_TYPE}'. "
                        "Please supply a Jira Service Management project key."
                    )
            except ConnectorValidationError:
                raise
            except Exception as e:
                # Propagate auth/permission errors; ignore type-fetch failures
                # (e.g. older Jira Server that omits projectTypeKey).
                if getattr(e, "status_code", None) in (401, 403, 429):
                    self._handle_jira_connector_settings_error(e)
                else:
                    logger.debug(
                        "Could not verify project type for '%s'; skipping JSM check.",
                        self.jira_project,
                    )
        else:
            super().validate_connector_settings()
