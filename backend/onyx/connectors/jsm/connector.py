import requests
from typing import Any, Iterable
from onyx.connectors.models import Section
from onyx.connectors.interfaces import PollConnector

class JSMConnector(PollConnector):
    """
    Connector for Jira Service Management (JSM).
    Note: JSM uses a different REST API surface compared to standard Jira Cloud.
    """
    def __init__(self, base_url: str, email: str, api_token: str):
        self.base_url = base_url.rstrip('/')
        self.auth = (email, api_token)

    def load_from_source(self) -> Iterable[Section]:
        # Using the JSM specific /request endpoint as requested by the maintainers
        # Reference: https://developer.atlassian.com/cloud/jira/service-desk/rest/api-group-request/
        url = f"{self.base_url}/rest/servicedeskapi/request"
        
        try:
            response = requests.get(url, auth=self.auth, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            requests_list = data.get("values", [])

            for req in requests_list:
                # Extracting key fields from the JSM request object
                summary = req.get("summary", "No Title")
                desc = req.get("issueDescription", "No content available.")
                # Self-link for the UI
                web_link = req.get("_links", {}).get("web", "")
                
                yield Section(
                    link=web_link,
                    content=f"Ticket: {summary}\n{desc}",
                    metadata={
                        "status": req.get("currentStatus", {}).get("status", "unknown"),
                        "request_id": req.get("issueId", ""),
                        "connector_type": "jsm"
                    }
                )
        except Exception as e:
            # Basic error handling for logging purposes
            print(f"JSM Connector Sync Error: {e}")
            return
