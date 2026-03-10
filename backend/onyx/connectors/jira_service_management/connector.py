"""
Jira Service Management Connector.

Inherits from the standard Jira connector since JSM shares the same
Jira REST API. The only material difference is that indexed documents
are tagged with DocumentSource.JIRA_SERVICE_MANAGEMENT instead of
DocumentSource.JIRA, so that JSM content is distinguishable from
regular Jira content in search results and permission sync.
"""

from typing import Any

from typing_extensions import override

from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import CheckpointOutput
from onyx.connectors.jira.access import get_project_permissions
from onyx.connectors.jira.connector import JiraConnector
from onyx.connectors.jira.connector import JiraConnectorCheckpoint
from onyx.connectors.models import Document


class JiraServiceManagementConnector(JiraConnector):
    """
    Connector for Jira Service Management (JSM) projects.

    Reuses all indexing, pagination, ADF parsing, hierarchy, and permission
    logic from the standard Jira connector. Overrides:
      - _load_from_checkpoint: re-tags yielded Documents with the JSM source type.
      - _get_project_permissions: ensures EE permission group IDs are prefixed
        with ``jira_service_management_`` instead of ``jira_``.
    """

    @override
    def _get_project_permissions(
        self, project_key: str, add_prefix: bool = False
    ) -> Any:
        """Get project permissions with the JSM-specific source for correct prefix."""
        cache_key = f"{project_key}:{'prefixed' if add_prefix else 'unprefixed'}"
        if cache_key not in self._project_permissions_cache:
            self._project_permissions_cache[cache_key] = get_project_permissions(
                jira_client=self.jira_client,
                jira_project=project_key,
                add_prefix=add_prefix,
                source=DocumentSource.JIRA_SERVICE_MANAGEMENT,
            )
        return self._project_permissions_cache[cache_key]

    @override
    def _load_from_checkpoint(
        self,
        jql: str,
        checkpoint: JiraConnectorCheckpoint,
        include_permissions: bool,
    ) -> CheckpointOutput[JiraConnectorCheckpoint]:
        """Wrap the parent generator, re-tagging Documents with the JSM source."""
        gen = super()._load_from_checkpoint(jql, checkpoint, include_permissions)
        try:
            while True:
                item = next(gen)
                if isinstance(item, Document):
                    item.source = DocumentSource.JIRA_SERVICE_MANAGEMENT
                yield item
        except StopIteration as e:
            return e.value  # the updated checkpoint
