"""Jira Service Management connector that extends the standard Jira connector.

Jira Service Management (JSM) uses the same Jira API as regular Jira but is
specialized for IT service management, customer support, and operations. This
connector provides a dedicated DocumentSource for JSM projects while reusing
all the indexing, pagination, and permission sync logic from JiraConnector.
"""

from typing import Any

from typing_extensions import override

from onyx.configs.app_configs import INDEX_BATCH_SIZE, JIRA_CONNECTOR_LABELS_TO_SKIP
from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.jira.connector import JiraConnector, build_jql_query
from onyx.connectors.jira.source_operations import is_cloud_gateway
from onyx.utils.logger import setup_logger

logger = setup_logger()


class JiraServiceManagementConnector(JiraConnector):
    """Connector for Jira Service Management projects.

    JSM uses the same Jira REST API as regular Jira, so this connector inherits
    all functionality from JiraConnector. The key difference is the document_source
    property, which categorizes JSM documents separately for tracking and filtering.

    This approach avoids code duplication while providing a distinct connector type
    for service management projects.
    """

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
        """Initialize the JSM connector with the same parameters as Jira connector.

        Args:
            jira_base_url: Base URL of the Jira instance (e.g., https://company.atlassian.net)
            project_key: Optional project key to filter by (e.g., "SUPPORT", "ITHELP")
            comment_email_blacklist: Email addresses whose comments should be excluded
            batch_size: Number of issues to fetch per API call
            labels_to_skip: Issue labels to exclude from indexing
            jql_query: Optional JQL query to further filter issues (takes precedence over project_key)
            scoped_token: Whether to use a scoped API token (Cloud Gateway)
        """
        super().__init__(
            jira_base_url=jira_base_url,
            project_key=project_key,
            comment_email_blacklist=comment_email_blacklist,
            batch_size=batch_size,
            labels_to_skip=labels_to_skip,
            jql_query=jql_query,
            scoped_token=scoped_token,
        )

    @override
    @property
    def document_source(self) -> DocumentSource:
        """Returns JIRA_SERVICE_MANAGEMENT to categorize JSM documents separately."""
        return DocumentSource.JIRA_SERVICE_MANAGEMENT

    def _get_service_desk_project_keys(self) -> list[str]:
        """Enumerate JSM project keys for Data Center deployments.
        
        Returns:
            List of project keys that are service desk projects.
            
        Raises:
            Exception: When project enumeration fails. Callers should handle
                this distinctly from the empty-list case.
        """
        projects = self.source_operations.list_projects()
        jsm_keys = [
            project["key"]
            for project in projects
            if project.get("projectTypeKey") == "service_desk"
        ]
        return jsm_keys

    def _resolve_jsm_scope_once(self) -> None:
        """Resolve and cache JSM project scope for Data Center Everything scope.
        
        For Data Center deployments with Everything scope, this caches the JSM
        project-key list to avoid repeated list_projects() calls during polling
        or retry runs. Only called when both project_key and jql_query are empty.
        """
        if hasattr(self, "_jsm_scope_cached"):
            return
        
        if not is_cloud_gateway(self.source_operations):
            self._jsm_project_keys_cache = self._get_service_desk_project_keys()
        self._jsm_scope_cached = True

    @override
    def _get_jql_query(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch | None
    ) -> str:
        """Build JQL query that restricts to service desk projects.
        
        When neither a custom JQL query nor a project key is specified (the
        "Everything" scope), this ensures only service desk projects are indexed,
        preventing regular Jira projects from being included via the JSM connector.
        
        On Atlassian Cloud, uses the projectType JQL field.
        On Data Center/Server, enumerates JSM projects and builds a project IN (...) clause.
        
        Args:
            start: Start time for the query window
            end: End time for the query window (None for open-ended)
            
        Returns:
            JQL query string restricted to service desk projects
        """
        # Resolve Everything scope JSM filter once for Data Center
        if not self.jql_query and not self.jira_project:
            self._resolve_jsm_scope_once()

        # Get JSM scope filter if in Everything scope, else use user config
        jsm_scope = self._get_jsm_scope_jql()
        jql_query = jsm_scope if jsm_scope else self.jql_query

        if jsm_scope == "id < 0":
            logger.warning(
                "No JSM projects found on Data Center instance. "
                "JSM connector will not index any issues."
            )

        return build_jql_query(
            project_key=self.jira_project,
            jql_query=jql_query,
            start=start,
            end=end,
        )

    def _get_jsm_scope_jql(self) -> str | None:
        """Build JSM scope filter for Everything scope, or None if scoped.
        
        Returns the JSM project filter when both project_key and jql_query are
        empty (Everything scope). Returns None when either is set, indicating
        the user has already scoped the connector.
        
        This is used by retry/reindex paths to apply JSM scope to key-based
        searches, ensuring non-JSM issues are not indexed as JSM documents.
        """
        if self.jql_query or self.jira_project:
            return None
        
        if is_cloud_gateway(self.source_operations):
            return "projectType = service_desk"
        else:
            if hasattr(self, "_jsm_project_keys_cache"):
                jsm_keys = self._jsm_project_keys_cache
            else:
                jsm_keys = self._get_service_desk_project_keys()
            
            if jsm_keys:
                keys_str = ", ".join(f'"{key}"' for key in jsm_keys)
                return f"project IN ({keys_str})"
            else:
                return "id < 0"

    @override
    def _search_issues_by_key(self, issue_keys: list[str]) -> list[dict[str, Any]]:
        """Search for issues by key, applying JSM scope for Everything.
        
        Overrides the base implementation to ensure that when the connector
        has Everything scope (no project_key or jql_query), only JSM issues
        are returned. This prevents a non-JSM issue from being indexed as
        JSM during retry or reindex operations.
        """
        # Resolve Everything scope JSM filter once for Data Center
        if not self.jql_query and not self.jira_project:
            self._resolve_jsm_scope_once()

        # Apply JSM scope if Everything scope, otherwise use base scoping
        jsm_scope = self._get_jsm_scope_jql()
        if jsm_scope:
            # Everything scope: add JSM filter to key search
            keys_jql: str = "key in (%s)" % ", ".join(f'"{key}"' for key in issue_keys)
            scoped_jql = f"({jsm_scope}) AND {keys_jql}"
            return list(self._search_all_issues(scoped_jql))
        else:
            # User-scoped: delegate to base implementation
            return super()._search_issues_by_key(issue_keys)
