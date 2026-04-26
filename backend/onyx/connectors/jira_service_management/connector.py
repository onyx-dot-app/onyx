"""
Jira Service Management (JSM) Connector for Onyx.

Indexes tickets from Jira Service Management (service desk) projects, including
service requests, incidents, problems, and change requests. Extends the base
Jira connector with JSM-specific fields: request type, SLA status, and
customer reporter information fetched from the JSM REST API.
"""

from __future__ import annotations

from typing import Any

from typing_extensions import override

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.app_configs import JIRA_CONNECTOR_LABELS_TO_SKIP
from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import CheckpointOutput
from onyx.connectors.jira.connector import JiraConnector
from onyx.connectors.jira.connector import JiraConnectorCheckpoint
from onyx.connectors.models import Document
from onyx.utils.logger import setup_logger

logger = setup_logger()

# JSM-specific field names for metadata
_FIELD_REQUEST_TYPE = "request_type"
_FIELD_SLA_BREACHED = "sla_breached"
_FIELD_SLA_NAME = "sla_name"
_FIELD_SLA_REMAINING_SECONDS = "sla_remaining_seconds"
_FIELD_CUSTOMER_REPORTER = "customer_reporter"


def _get_jsm_request_details(
    jira_base: str,
    issue_key: str,
    session: Any,
) -> dict[str, Any]:
    """Fetch JSM-specific fields for a ticket via the Service Desk API.

    Returns a dict with keys: request_type, sla_breached, sla_name,
    sla_remaining_seconds, customer_reporter. Missing fields are omitted.
    """
    result: dict[str, Any] = {}
    try:
        url = f"{jira_base}/rest/servicedeskapi/request/{issue_key}"
        resp = session.get(url, headers={"X-ExperimentalApi": "opt-in"})
        if resp.status_code != 200:
            return result
        data = resp.json()

        # Request type (e.g., "Get IT help", "Incident")
        rt = data.get("requestType")
        if rt and isinstance(rt, dict):
            rt_name = rt.get("name")
            if rt_name:
                result[_FIELD_REQUEST_TYPE] = rt_name

        # Customer reporter (the end-user who raised the request)
        reporter = data.get("reporter")
        if reporter and isinstance(reporter, dict):
            display_name = reporter.get("displayName")
            if display_name:
                result[_FIELD_CUSTOMER_REPORTER] = display_name

        # SLA information — iterate over SLA fields
        sla_list = data.get("sla", {}).get("values", [])
        for sla in sla_list:
            if not isinstance(sla, dict):
                continue
            # Only report the first SLA that is currently active or breached
            completed_cycles = sla.get("completedCycles", [])
            ongoing_cycle = sla.get("ongoingCycle")
            if ongoing_cycle and isinstance(ongoing_cycle, dict):
                breached = ongoing_cycle.get("breached", False)
                remaining = ongoing_cycle.get("remainingTime", {})
                remaining_secs = (
                    remaining.get("millis", 0) // 1000 if remaining else 0
                )
                sla_name = sla.get("name", "")
                result[_FIELD_SLA_NAME] = sla_name
                result[_FIELD_SLA_BREACHED] = str(breached).lower()
                result[_FIELD_SLA_REMAINING_SECONDS] = str(remaining_secs)
                break  # report first active SLA only
            elif completed_cycles:
                # Closed ticket — report last completed cycle breach status
                last = completed_cycles[-1]
                if isinstance(last, dict):
                    result[_FIELD_SLA_NAME] = sla.get("name", "")
                    result[_FIELD_SLA_BREACHED] = str(
                        last.get("breached", False)
                    ).lower()
                    break
    except Exception as e:
        logger.debug(
            f"Could not fetch JSM request details for {issue_key} — "
            f"skipping JSM-specific metadata. Error: {e}",
            exc_info=True,
        )
    return result


def _enrich_document_with_jsm_fields(
    document: Document,
    issue_key: str,
    jira_base: str,
    session: Any,
) -> Document:
    """Add JSM-specific metadata fields to an already-processed Document."""
    jsm_data = _get_jsm_request_details(jira_base, issue_key, session)
    if jsm_data:
        if document.metadata is None:
            document.metadata = {}
        document.metadata.update(jsm_data)
    return document


class JiraServiceManagementConnector(JiraConnector):
    """Connector for Jira Service Management (JSM) service desk projects.

    Behaves like the standard Jira connector but:
    - Restricts indexing to service desk project types by default.
    - Enriches each document with JSM-specific metadata: request type,
      SLA status, and customer reporter.
    - Reports source as DocumentSource.JIRA_SERVICE_MANAGEMENT.
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
    def _get_jql_query(
        self, start: float, end: float
    ) -> str:
        """Override base JQL to scope to service_desk project types by default."""
        base_jql = super()._get_jql_query(start, end)

        # If the caller already provided a custom JQL or project key, the parent
        # already scoped it — return as-is (caller has already constrained the query).
        if self.jql_query or self.jira_project:
            return base_jql

        # No scoping — add service_desk project type filter
        return f"project type = service_desk AND {base_jql}"

    @override
    def _load_from_checkpoint(
        self,
        jql: str,
        checkpoint: JiraConnectorCheckpoint,
        include_permissions: bool,
    ) -> CheckpointOutput[JiraConnectorCheckpoint]:
        """Wrap the parent generator to set JSM source and enrich with JSM metadata.

        Intercepts each Document yielded by the parent implementation to:
        1. Override document.source to DocumentSource.JIRA_SERVICE_MANAGEMENT.
        2. Enrich with JSM-specific metadata (request type, SLA, customer reporter)
           fetched from the JSM Service Desk REST API.

        Non-Document items (HierarchyNode, ConnectorFailure, checkpoint objects)
        pass through unchanged.
        """
        for item in super()._load_from_checkpoint(jql, checkpoint, include_permissions):
            if isinstance(item, Document):
                # Override the source type to differentiate JSM from plain Jira
                item.source = DocumentSource.JIRA_SERVICE_MANAGEMENT

                # Derive the Jira issue key from the document's metadata.
                # The parent connector always stores the issue key under "key".
                if self._jira_client is not None:
                    issue_key = item.metadata.get("key") if item.metadata else None
                    if issue_key:
                        item = _enrich_document_with_jsm_fields(
                            document=item,
                            issue_key=issue_key,
                            jira_base=self.jira_base,
                            session=self._jira_client._session,  # type: ignore[union-attr]
                        )
            yield item


if __name__ == "__main__":
    import os

    from tests.daily.connectors.utils import load_all_from_connector

    connector = JiraServiceManagementConnector(
        jira_base_url=os.environ["JSM_BASE_URL"],
        project_key=os.environ.get("JSM_PROJECT_KEY"),
        comment_email_blacklist=[],
    )

    connector.load_credentials(
        {
            "jira_user_email": os.environ["JIRA_USER_EMAIL"],
            "jira_api_token": os.environ["JIRA_API_TOKEN"],
        }
    )

    start = 0
    end = __import__("datetime").datetime.now().timestamp()

    result = load_all_from_connector(connector=connector, start=start, end=end)
    for doc in result.documents:
        print(f"[{doc.source}] {doc.id} — {doc.semantic_identifier}")
        print(f"  metadata: {doc.metadata}")
        print()
