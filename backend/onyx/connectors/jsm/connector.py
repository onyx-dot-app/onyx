"""Jira Service Management (JSM) connector for Onyx.

Indexes JSM service desk requests, enriching documents with request type,
SLA status, and customer information from the Service Desk REST API.
"""

import time
from collections.abc import Generator
from typing import Any
from typing import cast

from typing_extensions import override

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.app_configs import JIRA_CONNECTOR_LABELS_TO_SKIP
from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import CheckpointOutput
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.jira.connector import JiraConnector
from onyx.connectors.jira.connector import JiraConnectorCheckpoint
from onyx.connectors.models import Document
from onyx.utils.logger import setup_logger

logger = setup_logger()

# JSM issue types that represent service desk requests
_JSM_ISSUE_TYPES = [
    "Service Request",
    "Incident",
    "Problem",
    "Change",
    "Service Task",
    "Service Request with Approvals",
]

_JSM_JQL_TYPE_FILTER = (
    "issuetype in ("
    + ", ".join(f'"{t}"' for t in _JSM_ISSUE_TYPES)
    + ")"
)

__all__ = ["JsmConnector"]


class JsmConnector(JiraConnector):
    """Connector for Jira Service Management (JSM) service desk projects.

    Builds on JiraConnector to:
    - Scope indexing to JSM-specific issue types (Service Request, Incident, etc.)
    - Enrich documents with JSM metadata: request type, SLA status, customer info
    - Tag all documents with the JIRA_SERVICE_MANAGEMENT source

    Credentials are the same as the standard Jira connector:
      - jira_user_email
      - jira_api_token
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
        # Track whether the user supplied a custom JQL to preserve their intent
        self._user_supplied_jql = jql_query is not None

    @override
    def _get_jql_query(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
    ) -> str:
        """Build JQL query scoped to JSM service desk issue types.

        When no custom JQL is supplied, appends an issuetype filter so only
        service desk requests are indexed. Custom JQL is passed through as-is,
        trusting the operator to scope the query themselves.
        """
        base_jql = super()._get_jql_query(start, end)
        if self._user_supplied_jql:
            # Respect the caller's intent; they know which issues they want
            return base_jql
        return f"({base_jql}) AND {_JSM_JQL_TYPE_FILTER}"

    def _fetch_jsm_request_metadata(self, issue_key: str) -> dict[str, str]:
        """Fetch JSM-specific metadata from the Service Desk API.

        Returns a dict of additional metadata keys, or empty dict on failure.
        Requires the X-ExperimentalApi header to access the /rest/servicedeskapi
        endpoint on Jira Cloud.
        """
        if self._jira_client is None:
            return {}
        try:
            base_url = self._jira_client._options["server"].rstrip("/")
            url = f"{base_url}/rest/servicedeskapi/request/{issue_key}"
            resp = self._jira_client._session.get(
                url,
                headers={"X-ExperimentalApi": "opt-in"},
                timeout=10,
            )
            if resp.status_code != 200:
                return {}

            data = resp.json()
            meta: dict[str, str] = {}

            # Request type (e.g. "Get IT help", "Report a system problem")
            request_type = data.get("requestType") or {}
            if request_type:
                meta["jsm_request_type"] = str(request_type.get("name", ""))
                meta["jsm_request_type_id"] = str(request_type.get("id", ""))

            # Current status in JSM terms (differs from Jira status)
            current_status = data.get("currentStatus") or {}
            if current_status:
                meta["jsm_status"] = str(current_status.get("status", ""))
                meta["jsm_status_category"] = str(
                    current_status.get("statusCategory", "")
                )

            # Customer (the person who raised the request)
            reporter = data.get("reporter") or {}
            if reporter:
                meta["jsm_customer"] = str(reporter.get("displayName", ""))
                customer_email = reporter.get("emailAddress", "")
                if customer_email:
                    meta["jsm_customer_email"] = str(customer_email)

            # SLA breach indicator — check both completed and ongoing cycles.
            # An ongoingCycle that has already passed its breach time is a live
            # breach even though the cycle has not formally completed yet.
            now_ms = int(time.time() * 1000)
            sla_list = data.get("sla") or {}
            values = sla_list.get("values") or []
            breached = []
            for v in values:
                name = v.get("name", "SLA")
                # Check most recent completed cycle
                completed = v.get("completedCycles") or []
                if completed and completed[-1].get("breached"):
                    breached.append(name)
                    continue
                # Also flag if any ongoing cycle has already passed its breach time
                for cycle in v.get("ongoingCycles") or []:
                    if cycle.get("breached"):
                        breached.append(name)
                        break
                    breach_ts = (cycle.get("breachTime") or {}).get("epochMillis")
                    if breach_ts and breach_ts < now_ms:
                        breached.append(name)
                        break
            if breached:
                meta["jsm_sla_breached"] = ", ".join(breached)

            return meta

        except Exception as exc:
            logger.debug(
                "JSM Service Desk API request failed for %s: %s", issue_key, exc
            )
            return {}

    def _enrich_document(self, doc: Document) -> Document:
        """Stamp the document with JSM source and Service Desk metadata."""
        doc.source = DocumentSource.JIRA_SERVICE_MANAGEMENT

        # Rename legacy field names to JSM-specific ones
        for old_key, new_key in (
            ("request-type", "jsm_request_type"),
            ("customer-satisfaction", "jsm_satisfaction_score"),
        ):
            if old_key in doc.metadata:
                doc.metadata[new_key] = doc.metadata.pop(old_key)

        # Fetch additional metadata from the Service Desk API
        issue_key = doc.metadata.get("key", "")
        if issue_key:
            jsm_meta = self._fetch_jsm_request_metadata(issue_key)
            # Don't overwrite metadata already populated from the Jira API
            for k, v in jsm_meta.items():
                if k not in doc.metadata or not doc.metadata[k]:
                    doc.metadata[k] = v

        return doc

    def _wrap_generator_with_jsm_enrichment(
        self,
        generator: Generator[Any, None, JiraConnectorCheckpoint],
    ) -> CheckpointOutput[JiraConnectorCheckpoint]:
        """Yield items from *generator*, enriching Document items with JSM data."""
        try:
            while True:
                item = next(generator)
                if isinstance(item, Document):
                    item = self._enrich_document(item)
                yield item
        except StopIteration as exc:
            return cast(JiraConnectorCheckpoint, exc.value)

    @override
    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: JiraConnectorCheckpoint,
    ) -> CheckpointOutput[JiraConnectorCheckpoint]:
        gen = super().load_from_checkpoint(start, end, checkpoint)
        return self._wrap_generator_with_jsm_enrichment(gen)

    @override
    def load_from_checkpoint_with_perm_sync(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: JiraConnectorCheckpoint,
    ) -> CheckpointOutput[JiraConnectorCheckpoint]:
        gen = super().load_from_checkpoint_with_perm_sync(start, end, checkpoint)
        return self._wrap_generator_with_jsm_enrichment(gen)


if __name__ == "__main__":
    import os
    from datetime import datetime

    from tests.daily.connectors.utils import load_all_from_connector

    connector = JsmConnector(
        jira_base_url=os.environ["JIRA_BASE_URL"],
        project_key=os.environ.get("JIRA_PROJECT_KEY"),
    )
    connector.load_credentials(
        {
            "jira_user_email": os.environ["JIRA_USER_EMAIL"],
            "jira_api_token": os.environ["JIRA_API_TOKEN"],
        }
    )

    start = 0.0
    end = datetime.now().timestamp()
    result = load_all_from_connector(connector=connector, start=start, end=end)
    for doc in result.documents:
        print(doc)
