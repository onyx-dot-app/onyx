"""Jira Service Management (JSM) connector.

Indexes the tickets (customer requests) of a Jira Service Management project
as their own document source, enriching each one with customer-portal
metadata from the JSM Service Desk REST API: request type, portal status and
an SLA breach summary.

All indexing, checkpointing, slim-listing, hierarchy and permission-sync
behavior is inherited from the Jira connector - a JSM project is a regular
Jira project of type ``service_desk``. Only two things change here:

1. Indexed documents carry ``DocumentSource.JIRA_SERVICE_MANAGEMENT`` so they
   stay distinguishable (and independently filterable) from plain Jira issues.
2. Each document's metadata gains the JSM portal fields when the Service Desk
   API answers. Enrichment is best effort: when JSM is not installed, the
   credential lacks service-desk access, or a single request lookup fails,
   the ticket still indexes with the regular Jira fields.
"""

from collections.abc import Generator, Mapping
from typing import Any, ClassVar

from onyx.configs.constants import DocumentSource
from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.jira.connector import JiraConnector
from onyx.connectors.jira.source_operations import (
    JiraSourceOperations,
    sla_payload_has_more_pages,
)
from onyx.connectors.jira.utils import get_issue_field
from onyx.connectors.models import Document, HierarchyNode
from onyx.utils.logger import setup_logger

logger = setup_logger()

_FIELD_KEY = "key"
_FIELD_PROJECT = "project"
_FIELD_PROJECT_TYPE_KEY = "projectTypeKey"
_PROJECT_TYPE_SERVICE_DESK = "service_desk"

# Extra metadata keys this connector adds on top of the Jira ones.
META_REQUEST_TYPE = "request_type"
META_PORTAL_STATUS = "portal_status"
META_SLA_BREACHED = "sla_breached"


def _sla_breached_summary(sla_payload: Mapping[str, Any]) -> str | None:
    """Summarizes the SLA payload as "true"/"false" when it contains any
    cycle with a known breached state; None when nothing is known or when
    pagination is incomplete without a known breach."""
    cycles: list[bool] = []
    values = sla_payload.get("values")
    if isinstance(values, list):
        for value in values:
            if not isinstance(value, Mapping):
                continue
            ongoing = value.get("ongoingCycle")
            if isinstance(ongoing, Mapping) and "breached" in ongoing:
                cycles.append(bool(ongoing["breached"]))
            completed_cycles = value.get("completedCycles")
            if isinstance(completed_cycles, list):
                cycles.extend(
                    bool(completed["breached"])
                    for completed in completed_cycles
                    if isinstance(completed, Mapping) and "breached" in completed
                )
    if any(cycles):
        return "true"
    if not cycles or sla_payload_has_more_pages(sla_payload):
        return None
    return "false"


class JiraServiceManagementConnector(JiraConnector):
    """Connector for Jira Service Management customer portal tickets."""

    connector_source: ClassVar[DocumentSource] = DocumentSource.JIRA_SERVICE_MANAGEMENT

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._project_type_cache: dict[str, str | None] = {}

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        """Bind Jira credentials using the JSM source identifier."""
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

    def _issue_project_type(self, issue: dict[str, Any]) -> str | None:
        """Return the raw Jira projectTypeKey for an issue, resolving and
        caching via project lookup when the issue payload omits it."""
        project = get_issue_field(issue, _FIELD_PROJECT)
        if not project or not isinstance(project, dict):
            return None
        project_type = project.get(_FIELD_PROJECT_TYPE_KEY)
        if project_type is not None:
            return project_type

        project_key = project.get(_FIELD_KEY)
        if not project_key or not isinstance(project_key, str):
            return None

        if not hasattr(self, "_project_type_cache"):
            self._project_type_cache = {}

        if project_key in self._project_type_cache:
            return self._project_type_cache[project_key]

        try:
            if self._source_operations is not None:
                proj_data = self.source_operations.get_project(
                    project_key=project_key, fast=True
                )
                resolved_type = (proj_data or {}).get(_FIELD_PROJECT_TYPE_KEY)
            else:
                resolved_type = None
        except Exception:
            resolved_type = None

        self._project_type_cache[project_key] = resolved_type
        return resolved_type

    def _drops_issue(self, issue: dict[str, Any]) -> bool:
        """Everything-scope gate. With the default "Everything" scope the
        inherited JQL matches every project the credential can browse,
        including software projects. Ordinary Jira issues must not index
        under the JSM source, so drop issues whose project cannot be confirmed
        as a service desk. JQL-only and Project configurations define an explicit
        scope, so the gate applies to Everything only. If Jira omits
        projectTypeKey, the connector attempts to resolve it via project
        lookup. If it still remains unknown, the issue is not admitted under
        Everything scope (requiring an explicit scope to index)."""
        if self.jira_project or self.jql_query:
            return False
        project_type = self._issue_project_type(issue)
        return project_type != _PROJECT_TYPE_SERVICE_DESK

    def _include_issue_in_slim_listing(self, issue: dict[str, Any]) -> bool:
        """Applies the Everything-scope gate to slim-document listing too.
        Pruning diffs this listing against the indexed set; without the gate
        an issue that moved out of its service desk project would keep a
        stale JSM document forever."""
        return not self._drops_issue(issue)

    def _issue_to_items(
        self,
        issue: dict[str, Any],
        seen_hierarchy_node_ids: set[str],
        include_permissions: bool,
    ) -> Generator[Document | HierarchyNode, None, None]:
        """Convert a JSM issue into Onyx hierarchy nodes and enriched Documents."""
        if self._drops_issue(issue):
            return
        # In Project/JQL scopes the user picked the scope deliberately (JQL
        # may span project types); only skip the enrichment lookups for known
        # non-service-desk projects, which can never have portal metadata.
        enrich = self._issue_project_type(issue) in (None, _PROJECT_TYPE_SERVICE_DESK)
        for item in super()._issue_to_items(
            issue, seen_hierarchy_node_ids, include_permissions
        ):
            if isinstance(item, Document):
                self._mark_and_enrich_jsm_document(item, enrich=enrich)
            yield item

    def _mark_and_enrich_jsm_document(
        self, document: Document, *, enrich: bool = True
    ) -> None:
        """Sets the JSM source and adds portal metadata, best effort."""
        document.source = DocumentSource.JIRA_SERVICE_MANAGEMENT
        if not enrich:
            return

        issue_key = document.metadata.get(_FIELD_KEY)
        if not isinstance(issue_key, str) or not issue_key:
            return

        request = self.source_operations.get_service_desk_request(
            issue_key=issue_key, fast=True
        )
        if request is None:
            logger.debug(
                "No JSM portal metadata for %s: request lookup returned "
                "nothing (JSM absent or no service-desk access).",
                issue_key,
            )
        if isinstance(request, dict):
            request_type_obj = request.get("requestType")
            request_type = (
                request_type_obj.get("name")
                if isinstance(request_type_obj, dict)
                else None
            )
            if request_type and isinstance(request_type, str):
                document.metadata[META_REQUEST_TYPE] = request_type
            portal_status_obj = request.get("currentStatus")
            portal_status = (
                portal_status_obj.get("status")
                if isinstance(portal_status_obj, dict)
                else None
            )
            if portal_status and isinstance(portal_status, str):
                document.metadata[META_PORTAL_STATUS] = portal_status

        sla = self.source_operations.get_service_desk_sla(
            issue_key=issue_key, fast=True
        )
        if sla is None:
            logger.debug("No JSM SLA data for %s.", issue_key)
        if isinstance(sla, dict):
            summary = _sla_breached_summary(sla)
            if summary is not None:
                document.metadata[META_SLA_BREACHED] = summary

    def validate_connector_settings(self) -> None:
        """Regular Jira validation, plus a heads-up log when the configured
        project is not a service desk (still allowed - JQL scopes may span
        project types intentionally)."""
        super().validate_connector_settings()
        if self.jira_project is None or not self.jira_project:
            return
        try:
            project = self.source_operations.get_project(project_key=self.jira_project)
        except Exception:
            return  # the parent validator already reports unreachable projects
        project_type = (project or {}).get("projectTypeKey")
        if project_type and project_type != "service_desk":
            logger.warning(
                "Project %s has projectTypeKey '%s', not 'service_desk'. "
                "Tickets will still be indexed; JSM portal metadata may be "
                "absent.",
                self.jira_project,
                project_type,
            )
