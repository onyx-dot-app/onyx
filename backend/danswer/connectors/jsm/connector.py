import requests
from typing import Any
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.models import Document
from onyx.connectors.models import Section
from onyx.configs.constants import DocumentSource
from onyx.utils.logger import setup_logger

logger = setup_logger()

class JSMConnector(PollConnector):
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.email: str | None = None
        self.api_token: str | None = None

    def load_credentials(self, credentials: dict[str, Any]) -> None:
        """Requirement: Must implement load_credentials to be instantiable."""
        self.email = credentials.get("email")
        self.api_token = credentials.get("api_token")
        if not self.email or not self.api_token:
            raise ValueError("JSM Connector requires both 'email' and 'api_token'.")

    def poll_source(
        self, start: "float", end: "float"
    ) -> GenerateDocumentsOutput: 
        """Requirement: Must implement poll_source instead of load_from_source."""
        if not self.email or not self.api_token:
            raise RuntimeError("Connector not initialized with credentials.")

        url = f"{self.base_url}/rest/servicedeskapi/request"
        auth = (self.email, self.api_token)
        start_index = 0
        limit = 50

        while True:
            params = {"start": start_index, "limit": limit}
            try:
                response = requests.get(url, auth=auth, params=params, timeout=30)
                response.raise_for_status()
                data = response.json()
            except Exception as e:
                logger.exception(f"Failed to fetch from JSM: {e}")
                raise

            requests_list = data.get("values", [])
            doc_batch: list[Document] = []

            for req in requests_list:
                req_id = req.get("issueId")
                if req_id is None:
                    logger.warning(f"JSM ticket missing issueId, skipping: {req}")
                    continue
                req_id = str(req_id)
                summary = req.get("summary", "No Title")
                desc = req.get("issueDescription", "")
                web_link = req.get("_links", {}).get("web", "")

                doc_batch.append(
                    Document(
                        id=f"jsm_{req_id}",
                        sections=[
                            Section(link=web_link, text=f"Summary: {summary}\nDescription: {desc}")
                        ],
                        source=DocumentSource.JIRA,
                        semantic_identifier=summary,
                        metadata={
                            "status": req.get("currentStatus", {}).get("status", "unknown"),
                            "request_id": req_id,
                        },
                    )
                )

            if doc_batch:
                yield doc_batch

           is_last = data.get("isLastPage", True)
            if is_last or len(requests_list) < limit:
                break
            start_index += limit
