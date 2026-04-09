from collections.abc import Iterator

from onyx.connectors.jira.connector import JiraConnector
from onyx.connectors.jira.connector import JiraConnectorCheckpoint
from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import CheckpointOutput
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import Document
from onyx.connectors.models import DocumentFailure
from typing import Any
import logging

logger = logging.getLogger(__name__)


class JiraServiceManagementConnector(JiraConnector):
    @property
    def document_source(self) -> DocumentSource:
        return DocumentSource.JIRA_SERVICE_MANAGEMENT

    def _enrich_with_jsm_data(self, issue_key: str, doc: Document) -> Document:
        """Call /rest/servicedeskapi/request/{issue_key} and add JSM metadata."""
        if self._jsm_403_warned:
            return doc
        try:
            url = f"{self.jira_base}/rest/servicedeskapi/request/{issue_key}"
            resp = self.jira_client._session.get(url)
            if resp.status_code == 403:
                logger.warning("JSM API returned 403 - insufficient permissions. Skipping JSM enrichment.")
                self._jsm_403_warned = True
                return doc
            resp.raise_for_status()
            data = resp.json()
            doc.metadata["service_desk_id"] = str(data.get("serviceDeskId", ""))
            doc.metadata["request_type_id"] = str(data.get("requestTypeId", ""))
            status = data.get("currentStatus", {})
            doc.metadata["request_status"] = status.get("status", "")
            portal = data.get("_links", {}).get("web", "")
            doc.metadata["portal_url"] = portal
        except Exception as e:
            logger.warning(f"JSM enrichment failed for {issue_key}: {e}")
        return doc

    def _load_from_checkpoint(
        self,
        jql: str,
        checkpoint: JiraConnectorCheckpoint,
        include_permissions: bool,
    ) -> CheckpointOutput[JiraConnectorCheckpoint]:
        """Override to add JSM enrichment to documents."""
        for doc_or_failure_or_node in super()._load_from_checkpoint(jql, checkpoint, include_permissions):
            if isinstance(doc_or_failure_or_node, Document):
                issue_key = doc_or_failure_or_node.id.split("/")[-1]
                doc = self._enrich_with_jsm_data(issue_key, doc_or_failure_or_node)
                yield doc
            else:
                yield doc_or_failure_or_node
