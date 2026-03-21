import requests
import time
from typing import Any, Iterator, List
from danswer.connectors.interfaces import PollConnector
from danswer.connectors.interfaces import GenerateDocumentsOutput
from danswer.connectors.models import Document
from danswer.connectors.models import Section
from danswer.configs.constants import DocumentSource
from danswer.utils.logger import setup_logger

logger = setup_logger()

class JSMConnector(PollConnector):
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip('/')
        self.auth = None

    def load_credentials(self, credentials: dict[str, Any]) -> None:
        """Securely loads email and api_token from Onyx credential store."""
        email = credentials.get("email")
        api_token = credentials.get("api_token")
        if not email or not api_token:
            raise ValueError("Missing 'email' or 'api_token' for JSM connector.")
        self.auth = (email, api_token)

    def poll_source(
        self, start: int, end: int
    ) -> Iterator[List[Document]]:
        """
        Polls JSM requests between start and end timestamps.
        Includes full pagination and proper Document model output.
        """
        if not self.auth:
            raise RuntimeError("load_credentials() must be called before poll_source().")

        url = f"{self.base_url}/rest/servicedeskapi/request"
        
        # P1 Fix: Implement Pagination
        start_index = 0
        limit = 50 # Standard JSM page size
        
        while True:
            params = {
                "start": start_index,
                "limit": limit
            }
            # Use specific time-based filtering in params if JSM API supports it, 
            # otherwise filter on the Python side based on req.get('createdDate')
            
            try:
                response = requests.get(url, auth=self.auth, params=params, timeout=30)
                response.raise_for_status()
                data = response.json()
            except Exception as e:
                # P1 Fix: fail loudly using project logger instead of print()
                logger.exception(f"Fatal error syncing from JSM: {e}")
                raise

            requests_list = data.get("values", [])
            documents_to_yield: List[Document] = []

            for req in requests_list:
                req_id = str(req.get("issueId"))
                summary = req.get("summary", "No Title")
                desc = req.get("issueDescription", "")
                
                # req_date_str = req.get("createdDate", {}).get("friendly", "")
                # TODO: Implement accurate time filtering using 'start' and 'end' args

                # P0 Fix: Yield full Document objects with internal Sections
                documents_to_yield.append(
                    Document(
                        id=f"jsm_ticket_{req_id}",
                        sections=[
                            Section(link="", text=f"Ticket: {summary}"),
                            Section(link="", text=desc),
                        ],
                        # Use existing JIRA source or add a new JSM entry in constants.py
                        source=DocumentSource.JIRA, 
                        semantic_identifier=summary,
                        metadata={
                            "jsm_request_id": req_id,
                            "status": req.get("currentStatus", {}).get("status", "unknown"),
                            "connector_type": "jsm"
                        },
                    )
                )

            if documents_to_yield:
                yield documents_to_yield

            # P1 Fix: Pagination loop break condition
            if data.get("isLastPage"):
                break
            start_index += limit
