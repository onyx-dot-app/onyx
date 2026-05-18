from collections.abc import Callable
from collections.abc import Generator
from datetime import datetime
from datetime import timezone
from typing import Any

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import Document
from onyx.connectors.models import TextSection
from onyx.connectors.jsm.client import JSMClient
from onyx.connectors.jira.utils import extract_text_from_adf
from onyx.utils.logger import setup_logger

logger = setup_logger()

class JiraServiceManagementConnector(LoadConnector, PollConnector):
    def __init__(self, **kwargs: Any):
        self.jira_base_url = kwargs.get("jira_base_url", "").rstrip("/")
        self.project_key = kwargs.get("project_key")
        self.batch_size = INDEX_BATCH_SIZE
        self._client: JSMClient | None = None

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self._client = JSMClient(self.jira_base_url, credentials)
        return None

    def _iterate_requests(
        self, time_filter: Callable[[datetime], bool] | None = None
    ) -> GenerateDocumentsOutput:
        if not self._client:
            raise ValueError("Client not initialized")

        service_desk_id = None
        if self.project_key:
            service_desk_id = self._client.get_service_desk_id(self.project_key)
            if not service_desk_id:
                logger.error(f"Service desk not found for project key: {self.project_key}")
                return

        start = 0
        limit = 50
        doc_batch: list[Document] = []

        while True:
            response = self._client.get_requests(service_desk_id, start=start, limit=limit)
            requests_data = response.get("values", [])
            if not requests_data:
                break

            for req in requests_data:
                req_key = req.get("issueKey")
                created_date_data = req.get("createdDate", {})
                updated_date = None
                if isinstance(created_date_data, dict):
                    created_date_str = created_date_data.get("iso8601")
                    if created_date_str:
                        try:
                            # Python 3.11 supports Z and most ISO formats
                            updated_date = datetime.fromisoformat(created_date_str.replace("Z", "+00:00"))
                        except ValueError:
                            logger.warning(f"Could not parse date: {created_date_str}")

                if time_filter and updated_date and not time_filter(updated_date):
                    continue

                # JSM API returns description in a complex way sometimes. 
                # If it's a dict, it might be ADF.
                raw_description = req.get("description")
                if isinstance(raw_description, dict):
                    description = extract_text_from_adf(raw_description)
                else:
                    description = str(raw_description or "")

                # Fetch comments
                try:
                    comments_response = self._client.get_comments(req_key)
                    comments_data = comments_response.get("values", [])
                    comment_texts = []
                    for comment in comments_data:
                        body = comment.get("body")
                        if isinstance(body, dict):
                            # Comments in JSM also use ADF or a dict structure
                            text = body.get("text") or extract_text_from_adf(body)
                        else:
                            text = str(body or "")
                        if text:
                            comment_texts.append(f"Comment: {text}")
                    
                    comment_text = "\n".join(comment_texts)
                except Exception as e:
                    logger.error(f"Failed to fetch comments for {req_key}: {e}")
                    comment_text = ""

                full_content = f"{description}\n\n{comment_text}"
                
                # Link to the issue in the standard Jira UI (always works)
                doc_link = f"{self.jira_base_url}/browse/{req_key}"

                doc_batch.append(
                    Document(
                        id=req_key,
                        sections=[TextSection(link=doc_link, text=full_content)],
                        source=DocumentSource.JIRA_SERVICE_MANAGEMENT,
                        semantic_identifier=f"{req_key}: {req.get('summary')}",
                        metadata={
                            "status": req.get("currentStatus", {}).get("status", ""),
                            "reporter": req.get("reporter", {}).get("displayName", ""),
                        },
                        doc_updated_at=updated_date
                    )
                )

                if len(doc_batch) >= self.batch_size:
                    yield doc_batch
                    doc_batch = []

            if response.get("isLastPage"):
                break
            start += limit

        if doc_batch:
            yield doc_batch

    def load_from_state(self) -> GenerateDocumentsOutput:
        yield from self._iterate_requests()

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        start_time = datetime.fromtimestamp(start, tz=timezone.utc)
        end_time = datetime.fromtimestamp(end, tz=timezone.utc)
        yield from self._iterate_requests(
            time_filter=lambda t: start_time <= t <= end_time
        )
    
    def validate_connector_settings(self) -> None:
        if not self.jira_base_url.startswith("https://") and not self.jira_base_url.startswith("http://"):
             raise ValueError("Jira Base URL must start with http:// or https://")
        
        if not self._client:
             raise ValueError("Client not initialized (credentials missing)")
        
        # Test basic connectivity by listing service desks (limited to 1)
        try:
            self._client.get_requests(limit=1)
        except Exception as e:
            raise ValueError(f"Failed to connect to JSM API: {e}")
