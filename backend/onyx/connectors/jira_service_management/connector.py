"""Jira Service Management (JSM) connector.

Indexes service desk tickets (requests, incidents, problems, changes) from
Jira Service Management projects.  Reuses all pagination, checkpointing,
and permission-sync logic from JiraConnector; the only additions are:

* DocumentSource.JIRA_SERVICE_MANAGEMENT is stamped on every yielded
  document so that JSM content is searchable as a distinct source type.
* When no project_key or custom jql_query is provided the connector
  automatically restricts indexing to the accessible Jira Service
  Management (service desk) projects.
* validate_connector_settings errors when a caller supplies a project_key
  that belongs to a non-service-desk project.
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
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import HierarchyNode
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger

logger = setup_logger()

_CT = TypeVar("_CT")

# Atlassian's REST API reports Jira Service Management projects with the
# projectTypeKey "service_desk" (the product was formerly "Jira Service Desk").
_JSM_PROJECT_TYPE = "service_desk"


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

    # Cache of accessible JSM project keys, populated lazily on first use so
    # that repeated checkpoint loads don't re-list projects on every call.
    _jsm_project_keys_cache: list[str] | None = None

    def _get_jql_query(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
    ) -> str:
        base_jql = super()._get_jql_query(start, end)

        # If the caller already scoped the query (custom JQL or a specific
        # project key), trust them and don't add any project-type filter.
        if self.jql_query or self.jira_project:
            return base_jql

        # No scope specified: restrict to Jira Service Management (service
        # desk) projects.  Jira has no portable "project type" JQL field, so we
        # enumerate the accessible JSM projects and filter by key.
        jsm_project_keys = self._get_service_desk_project_keys()
        if not jsm_project_keys:
            # Couldn't determine any JSM projects (none accessible, or the
            # listing endpoint is unavailable); fall back to the base query
            # rather than emitting invalid JQL.
            return base_jql

        keys = ", ".join(f'"{key}"' for key in jsm_project_keys)
        return f"({base_jql}) AND project in ({keys})"

    def _get_service_desk_project_keys(self) -> list[str]:
        """Return the keys of all accessible Jira Service Management projects."""
        if self._jsm_project_keys_cache is not None:
            return self._jsm_project_keys_cache

        try:
            projects = self.jira_client.projects()
        except Exception:
            logger.warning(
                "Could not list Jira projects to scope to Service Management; "
                "indexing will not be auto-restricted to JSM projects."
            )
            self._jsm_project_keys_cache = []
            return []

        keys = [
            project.key
            for project in projects
            if getattr(project, "projectTypeKey", None) == _JSM_PROJECT_TYPE
        ]
        self._jsm_project_keys_cache = keys
        return keys

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
        # When a project key is given (without custom JQL) we validate the
        # project AND confirm it's a JSM (service desk) project in a single
        # project() call, avoiding the redundant call super() would make.
        if self.jira_project and not self.jql_query:
            if self._jira_client is None:
                raise ConnectorMissingCredentialError("Jira")
            try:
                project = self.jira_client.project(self.jira_project)
            except Exception as e:
                # Surface auth / permission / not-found / rate-limit errors
                # exactly as the base connector does (always raises).
                self._handle_jira_connector_settings_error(e)
                return

            project_type = getattr(project, "projectTypeKey", None)
            # Older Jira Server may omit projectTypeKey; only enforce the check
            # when the field is actually present.
            if project_type and project_type != _JSM_PROJECT_TYPE:
                raise ConnectorValidationError(
                    f"Project '{self.jira_project}' has project type "
                    f"'{project_type}', not a Jira Service Management "
                    f"(service desk, '{_JSM_PROJECT_TYPE}') project. "
                    "Please supply a JSM project key."
                )
        else:
            super().validate_connector_settings()
