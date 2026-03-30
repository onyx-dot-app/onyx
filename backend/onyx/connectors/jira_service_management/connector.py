"""Jira Service Management (JSM) connector for Onyx.

Extends the base JiraConnector to index JSM-specific ticket data including
service requests, incidents, problems, changes, and SLA information.
"""

from typing import Any

from jira.resources import Issue
from typing_extensions import override

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.app_configs import JIRA_CONNECTOR_LABELS_TO_SKIP
from onyx.configs.constants import DocumentSource
from onyx.connectors.jira.connector import JiraConnector
from onyx.connectors.jira.connector import process_jira_issue
from onyx.connectors.jira.utils import best_effort_get_field_from_issue
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import Document
from onyx.utils.logger import setup_logger


logger = setup_logger()

# JSM issue type names (title case to match Jira's canonical names)
_JSM_ISSUE_TYPES = (
    "Service Request",
    "Service Request with Approvals",
    "Incident",
    "Problem",
    "Change",
)

# Dynamic field name patterns for discovery via /rest/api/2/field
# JSM custom field IDs vary per instance, so we discover them dynamically.
_FIELD_NAME_REQUEST_TYPE = ("request type", "customer request type")
_FIELD_NAME_TIME_TO_FIRST_RESPONSE = ("time to first response",)
_FIELD_NAME_TIME_TO_RESOLUTION = ("time to resolution",)

# Metadata keys for JSM-specific fields
_FIELD_REQUEST_TYPE = "request_type"
_FIELD_TIME_TO_FIRST_RESPONSE = "time_to_first_response"
_FIELD_TIME_TO_RESOLUTION = "time_to_resolution"
_FIELD_SLA_BREACHED = "sla_breached"


def _extract_sla_display(sla_value: Any) -> tuple[str | None, bool]:
    """Extract a human-readable SLA string and breach flag from a JSM SLA field value.

    JSM SLA fields have varying structures across Cloud and Server. This function
    tries several known shapes and returns (display_string, is_breached).
    """
    if sla_value is None:
        return None, False

    breached = False

    # Cloud: SLA field is often a dict with ongoingCycle / completedCycles
    if isinstance(sla_value, dict):
        ongoing = sla_value.get("ongoingCycle")
        if isinstance(ongoing, dict):
            breached = ongoing.get("breached", False)
            remaining = ongoing.get("remainingTime", {})
            if isinstance(remaining, dict):
                friendly = remaining.get("friendly")
                if friendly:
                    return str(friendly), breached
            # Breached but no remaining time display
            if breached:
                return "Breached", True

        # Try completedCycles
        completed = sla_value.get("completedCycles")
        if isinstance(completed, list) and completed:
            last = completed[-1]
            if isinstance(last, dict):
                breached = breached or last.get("breached", False)
                elapsed = last.get("elapsedTime", {})
                if isinstance(elapsed, dict):
                    friendly = elapsed.get("friendly")
                    if friendly:
                        return str(friendly), breached
                # Breached but no elapsed time display
                if breached:
                    return "Breached", True

    # Server / simple string
    if isinstance(sla_value, str):
        return sla_value, False

    # Fallback: try .name attribute (some jira resource objects)
    name = getattr(sla_value, "name", None)
    if name:
        return str(name), False

    # If breached but no display could be extracted, provide fallback
    if breached:
        return "Breached", True

    return None, False


def _extract_request_type_name(rt_value: Any) -> str | None:
    """Extract request type display name from a JSM request type field value."""
    if rt_value is None:
        return None

    if isinstance(rt_value, str):
        return rt_value

    # Cloud: dict with requestType.name
    if isinstance(rt_value, dict):
        rt = rt_value.get("requestType")
        if isinstance(rt, dict):
            return rt.get("name")
        # Fallback: direct name key
        return rt_value.get("name") or rt_value.get("value")

    # Jira resource object
    name = getattr(rt_value, "name", None) or getattr(rt_value, "value", None)
    if name:
        return str(name)

    return None


class JiraServiceManagementConnector(JiraConnector):
    """Extends JiraConnector to index Jira Service Management (JSM) tickets.

    Adds JSM-specific enrichment:
    - Request type (discovered dynamically, not hard-coded)
    - SLA time-to-first-response
    - SLA time-to-resolution
    - SLA breach flags

    All JiraConnector capabilities are inherited:
    checkpoint-based incremental sync, slim docs, permission sync.
    """

    def __init__(
        self,
        jira_base_url: str,
        service_desk_id: str | None = None,
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
        self.service_desk_id = service_desk_id
        self._jsm_field_map: dict[str, str] | None = None

    def _discover_jsm_fields(self) -> dict[str, str]:
        """Discover JSM custom field IDs dynamically via /rest/api/2/field.

        JSM uses custom fields whose IDs (e.g. customfield_10010) vary per
        instance. This method fetches the full field list once and caches the
        mapping from logical name to field ID.

        Returns:
            Mapping of logical_name -> field_id (e.g. {"request_type": "customfield_10010"}).
        """
        if self._jsm_field_map is not None:
            return self._jsm_field_map

        field_map: dict[str, str] = {}
        try:
            all_fields = self.jira_client.fields()
            for field in all_fields:
                field_name = (field.get("name") or "").lower()
                field_id = field.get("id", "")

                if any(pat in field_name for pat in _FIELD_NAME_REQUEST_TYPE):
                    field_map["request_type"] = field_id
                elif any(
                    pat in field_name for pat in _FIELD_NAME_TIME_TO_FIRST_RESPONSE
                ):
                    field_map["time_to_first_response"] = field_id
                elif any(
                    pat in field_name for pat in _FIELD_NAME_TIME_TO_RESOLUTION
                ):
                    field_map["time_to_resolution"] = field_id

            logger.debug(f"Discovered JSM fields: {field_map}")
        except Exception:
            logger.warning(
                "Could not discover JSM custom fields; SLA enrichment will be skipped",
                exc_info=True,
            )

        self._jsm_field_map = field_map
        return field_map

    def _enrich_document_with_jsm_metadata(
        self, document: Document, issue: Issue
    ) -> Document:
        """Add JSM-specific metadata (request type, SLA info) to a document."""
        field_map = self._discover_jsm_fields()

        # Request type
        rt_field_id = field_map.get("request_type")
        if rt_field_id:
            rt_value = best_effort_get_field_from_issue(issue, rt_field_id)
            rt_name = _extract_request_type_name(rt_value)
            if rt_name:
                document.metadata[_FIELD_REQUEST_TYPE] = rt_name

        any_breached = False

        # Time to first response
        ttfr_field_id = field_map.get("time_to_first_response")
        if ttfr_field_id:
            ttfr_value = best_effort_get_field_from_issue(issue, ttfr_field_id)
            ttfr_display, ttfr_breached = _extract_sla_display(ttfr_value)
            if ttfr_display:
                document.metadata[_FIELD_TIME_TO_FIRST_RESPONSE] = ttfr_display
            any_breached = any_breached or ttfr_breached

        # Time to resolution
        ttr_field_id = field_map.get("time_to_resolution")
        if ttr_field_id:
            ttr_value = best_effort_get_field_from_issue(issue, ttr_field_id)
            ttr_display, ttr_breached = _extract_sla_display(ttr_value)
            if ttr_display:
                document.metadata[_FIELD_TIME_TO_RESOLUTION] = ttr_display
            any_breached = any_breached or ttr_breached

        if any_breached:
            document.metadata[_FIELD_SLA_BREACHED] = "true"

        # Override source to JSM
        document.source = DocumentSource.JIRA_SERVICE_MANAGEMENT

        return document

    def _get_jsm_jql_filter(self) -> str:
        """Build a JQL filter clause for JSM issue types."""
        type_list = ", ".join(f'"{t}"' for t in _JSM_ISSUE_TYPES)
        return f"issuetype in ({type_list})"

    @override
    def _get_jql_query(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
    ) -> str:
        """Override to inject JSM issue type filter and service desk scoping.

        When ``service_desk_id`` is provided and no ``project_key`` or custom
        ``jql_query`` already scopes the query, a ``project =`` clause is
        prepended so the search is limited to that specific service desk project.
        The JSM issue-type filter is always appended (unless the caller supplied
        a custom JQL without a ``service_desk_id``, in which case we trust the
        caller's intent).
        """
        base_jql = super()._get_jql_query(start, end)

        # If user provided a custom JQL and no service_desk_id, trust the user
        if self.jql_query and not self.service_desk_id:
            return base_jql

        clauses: list[str] = [f"({base_jql})"]

        # Scope to the specific service desk project when provided and not
        # already covered by project_key or a custom JQL.
        if self.service_desk_id and not self.jira_project and not self.jql_query:
            # service_desk_id is treated as a Jira project key (JSM project
            # keys are valid JQL project identifiers).
            clauses.append(f"project = {self.service_desk_id}")

        # Always restrict to JSM issue types so we don't pull regular Jira
        # issues when no project scoping is present.
        clauses.append(self._get_jsm_jql_filter())

        return " AND ".join(clauses)

    @override
    def _enrich_document(self, document: Document, issue: Issue) -> Document:
        """Override hook to inject JSM metadata into each document."""
        return self._enrich_document_with_jsm_metadata(document, issue)


def process_jsm_issue(
    connector: "JiraServiceManagementConnector",
    issue: Issue,
    parent_hierarchy_raw_node_id: str | None = None,
) -> Document | None:
    """Process a Jira issue into a JSM-enriched Document.

    Uses the base process_jira_issue for core extraction, then enriches
    with JSM-specific metadata.
    """
    document = process_jira_issue(
        jira_base_url=connector.jira_base,
        issue=issue,
        comment_email_blacklist=connector.comment_email_blacklist,
        labels_to_skip=connector.labels_to_skip,
        parent_hierarchy_raw_node_id=parent_hierarchy_raw_node_id,
    )
    if document is None:
        return None

    return connector._enrich_document_with_jsm_metadata(document, issue)
