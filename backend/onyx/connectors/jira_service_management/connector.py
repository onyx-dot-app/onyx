from collections.abc import Generator
from datetime import datetime
from datetime import timezone
from typing import Any

import requests
from requests.auth import HTTPBasicAuth
from typing_extensions import override

from onyx.configs.app_configs import JIRA_SLIM_PAGE_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import CheckpointedConnectorWithPermSync
from onyx.connectors.interfaces import CheckpointOutput
from onyx.connectors.interfaces import IndexingHeartbeatInterface
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import ConnectorCheckpoint
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import DocumentFailure
from onyx.connectors.models import EntityFailure
from onyx.connectors.models import SlimDocument
from onyx.connectors.models import TextSection
from onyx.utils.logger import setup_logger

logger = setup_logger()


class JiraServiceManagementConnector(
    CheckpointedConnectorWithPermSync[ConnectorCheckpoint]
):
    def __init__(self, **kwargs: Any) -> None:
        self.jira_url = kwargs.get("jira_url", "").strip().rstrip("/")
        self.service_desk_id = kwargs.get("service_desk_id", "").strip()

        if not self.jira_url:
            raise ConnectorMissingCredentialError("JiraServiceManagement")

        # Enforce clean base URL structure
        if not self.jira_url.startswith(("http://", "https://")):
            self.jira_url = f"https://{self.jira_url}"

        # Initialize credentials from kwargs if present (helps unit tests)
        self.jira_user_email = kwargs.get("jira_user_email", "").strip()
        self.jira_api_token = kwargs.get("jira_api_token", "").strip()
        self.auth = None
        if self.jira_user_email and self.jira_api_token:
            self.auth = HTTPBasicAuth(self.jira_user_email, self.jira_api_token)

        self.headers = {
            "Accept": "application/json",
            "X-ExperimentalApi": "opt-in",  # Required for certain advanced JSM service desk endpoints
        }

    @property
    def source(self) -> DocumentSource:
        return DocumentSource.JIRA_SERVICE_MANAGEMENT

    def load_credentials(self, credentials: dict[str, Any]) -> None:
        self.jira_user_email = credentials.get("jira_user_email", "").strip()
        self.jira_api_token = credentials.get("jira_api_token", "").strip()

        if not self.jira_user_email or not self.jira_api_token:
            raise ConnectorMissingCredentialError("JiraServiceManagement")

        self.auth = HTTPBasicAuth(self.jira_user_email, self.jira_api_token)

    def _get_service_desks(self) -> list[str]:
        """Fetches target service desk IDs or discovers all accessible desks."""
        if self.service_desk_id:
            return [self.service_desk_id]

        service_desks = []
        url = f"{self.jira_url}/rest/servicedeskapi/servicedesk"
        start = 0
        limit = JIRA_SLIM_PAGE_SIZE

        while True:
            params = {"start": start, "limit": limit}
            try:
                response = requests.get(
                    url, auth=self.auth, headers=self.headers, params=params
                )
                response.raise_for_status()
                data = response.json()

                values = data.get("values", [])
                for sd in values:
                    if "id" in sd:
                        service_desks.append(str(sd["id"]))

                if data.get("isLastPage", True) or not values:
                    break
                start += len(values)
            except Exception as e:
                logger.error("Error discovering JSM service desks: %s", e)
                break

        return service_desks

    def _get_customer_requests(
        self, service_desk_id: str, start_time: SecondsSinceUnixEpoch
    ) -> Generator[list[dict[str, Any]], None, None]:
        """Yields pages of JSM customer requests updated after start_time."""
        url = f"{self.jira_url}/rest/servicedeskapi/search/request"
        start = 0
        limit = JIRA_SLIM_PAGE_SIZE

        # Use JSM-specific request filtering
        while True:
            # Service desk filtering combined with update-time filtering if checkpoint exists
            jql = f"serviceDesk = {service_desk_id}"
            if start_time > 0:
                dt = datetime.fromtimestamp(start_time, tz=timezone.utc)
                jql += f" AND updated >= '{dt.strftime('%Y-%m-%d %H:%M')}'"

            jql += " ORDER BY updated ASC"

            payload = {"jql": jql, "start": start, "limit": limit}

            try:
                response = requests.post(
                    url, auth=self.auth, headers=self.headers, json=payload
                )
                response.raise_for_status()
                data = response.json()

                values = data.get("values", [])
                if not values:
                    break

                yield values

                if data.get("isLastPage", True) or len(values) < limit:
                    break

                start += len(values)
            except Exception as e:
                logger.error(
                    "Failed to fetch requests for service desk %s: %s",
                    service_desk_id,
                    e,
                )
                raise e

    def retrieve_all_slim_docs(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> Generator[SlimDocument | ConnectorFailure, None, None]:
        service_desks = self._get_service_desks()

        for sd_id in service_desks:
            try:
                for request_batch in self._get_customer_requests(sd_id, start):
                    for req in request_batch:
                        req_key = req.get("issueKey")
                        if not req_key:
                            continue

                        # Extract timestamp verification fields safely (using updatedDate as identified by greptile)
                        updated_data = req.get("updatedDate", {})
                        epoch_ms = updated_data.get("epochMillis")

                        if epoch_ms:
                            updated_ts = int(epoch_ms / 1000)
                            if updated_ts > end:
                                continue

                        yield SlimDocument(
                            id=req_key,
                        )
            except Exception as e:
                logger.error("Fatal iteration failure on service desk %s: %s", sd_id, e)
                yield ConnectorFailure(
                    failed_entity=EntityFailure(entity_id=f"jsm_desk_{sd_id}"),
                    failure_message=str(e),
                    exception=e,
                )

    def _fetch_request_comments(self, issue_key: str) -> list[str]:
        """Extracts customer-visible public comments from the ticket thread."""
        comments = []
        url = f"{self.jira_url}/rest/servicedeskapi/request/{issue_key}/comment"
        start = 0
        limit = JIRA_SLIM_PAGE_SIZE

        while True:
            params = {"start": start, "limit": limit}
            try:
                response = requests.get(
                    url, auth=self.auth, headers=self.headers, params=params
                )
                if response.status_code == 404:
                    break
                response.raise_for_status()
                data = response.json()

                values = data.get("values", [])
                for comment in values:
                    # Filter for customer-visible public comments only (identified by cubic)
                    if not comment.get("public", True):
                        continue
                    body = comment.get("body", "")
                    if body:
                        comments.append(body)

                if data.get("isLastPage", True) or not values:
                    break
                start += len(values)
            except Exception as e:
                logger.warning(
                    "Could not pull comments for JSM ticket %s: %s", issue_key, e
                )
                break

        return comments

    def retrieve_docs(
        self,
        slim_docs: list[SlimDocument],
        heartbeat_interface: IndexingHeartbeatInterface,
    ) -> Generator[Document | ConnectorFailure, None, None]:
        for slim_doc in slim_docs:
            if heartbeat_interface.should_stop():
                break

            issue_key = slim_doc.id
            url = f"{self.jira_url}/rest/servicedeskapi/request/{issue_key}"

            try:
                response = requests.get(url, auth=self.auth, headers=self.headers)
                if response.status_code == 404:
                    continue
                response.raise_for_status()
                req_data = response.json()

                # Extract request properties
                summary = req_data.get("summary", "")
                description = req_data.get("description", "")

                sections = []
                browse_link = (
                    f"{self.jira_url}/servicedesk/customer/portal/all/{issue_key}"
                )

                if description:
                    sections.append(TextSection(text=description, link=browse_link))

                # Append conversational context sections from comments
                comments = self._fetch_request_comments(issue_key)
                for comment in comments:
                    sections.append(TextSection(text=comment, link=browse_link))

                # Extract dates safely for RAG temporal weighting
                created_date_data = req_data.get("createdDate", {})
                epoch_ms = created_date_data.get("epochMillis")
                doc_date = (
                    datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc)
                    if epoch_ms
                    else datetime.now(timezone.utc)
                )

                yield Document(
                    id=issue_key,
                    sections=sections,
                    source=self.source,
                    metadata={
                        "service_desk_id": str(
                            req_data.get("serviceDeskId", "unknown")
                        ),
                        "status": req_data.get("currentStatus", {}).get(
                            "status", "Unknown"
                        ),
                        "request_type": req_data.get("requestType", {}).get(
                            "name", "Generic"
                        ),
                    },
                    semantic_identifier=summary,
                    title=f"[{issue_key}] {summary}",
                    doc_updated_at=doc_date,
                )
            except Exception as e:
                logger.error(
                    "Failed parsing details for JSM ticket %s: %s", issue_key, e
                )
                yield ConnectorFailure(
                    failed_document=DocumentFailure(document_id=issue_key),
                    failure_message=str(e),
                    exception=e,
                )

    @override
    def build_dummy_checkpoint(self) -> ConnectorCheckpoint:
        return ConnectorCheckpoint(has_more=False)

    @override
    def validate_checkpoint_json(self, checkpoint_json: str) -> ConnectorCheckpoint:
        return ConnectorCheckpoint.model_validate_json(checkpoint_json)

    @override
    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: ConnectorCheckpoint,
    ) -> CheckpointOutput[ConnectorCheckpoint]:
        slim_docs: list[SlimDocument] = []
        for item in self.retrieve_all_slim_docs(start, end):
            if isinstance(item, SlimDocument):
                slim_docs.append(item)
            elif isinstance(item, ConnectorFailure):
                yield item

        class DummyHeartbeat(IndexingHeartbeatInterface):
            def should_stop(self) -> bool:
                return False

            def progress(self, *args: Any, **kwargs: Any) -> None:
                pass

        heartbeat = DummyHeartbeat()
        for doc_or_failure in self.retrieve_docs(slim_docs, heartbeat):
            yield doc_or_failure

        checkpoint.has_more = False
        return checkpoint

    @override
    def load_from_checkpoint_with_perm_sync(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: ConnectorCheckpoint,
    ) -> CheckpointOutput[ConnectorCheckpoint]:
        return (yield from self.load_from_checkpoint(start, end, checkpoint))
