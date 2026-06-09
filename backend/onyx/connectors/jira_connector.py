import base64
from collections.abc import Generator
from typing import Any
import requests

from onyx.connectors.interfaces import PollConnector
from onyx.configs.constants import DocumentSource
from onyx.connectors.models import Document
from onyx.connectors.models import TextSection
from onyx.utils.logger import setup_logger

logger = setup_logger()

class JiraConnector(PollConnector):
    def __init__(self, **kwargs: Any) -> None:
        # Configuration parameters will be injected via load_credentials
        self.url = ""
        self.project_key = ""
        self.headers: dict[str, str] = {}

    def load_credentials(self, credential_json: dict[str, Any]) -> None:
        """
        Extracts credentials from the provided JSON and builds the 
        Base64 encoded Authorization header.
        """
        username = credential_json.get("username")
        token = credential_json.get("token")
        self.url = credential_json.get("url", "").rstrip("/")
        self.project_key = credential_json.get("project_key", "")
        
        if not username or not token:
            logger.error("Missing username or token in Jira credentials.")
            return

        auth_str = f"{username}:{token}"
        encoded_auth = base64.b64encode(auth_str.encode("utf-8")).decode("utf-8")
        self.headers = {
            "Authorization": f"Basic {encoded_auth}",
            "Content-Type": "application/json"
        }

    @property
    def source(self) -> DocumentSource:
        return DocumentSource.JIRA_SERVICE_MANAGEMENT

    def load_from_state(self) -> Generator[list[Document], None, None]:
        """
        Fetches all tickets from the specified Jira Service Management 
        project using pagination and yields them as Onyx Documents.
        """
        if not self.url or not self.project_key:
            logger.error("Connector not properly initialized with URL and Project Key.")
            return

        start_at = 0
        max_results = 50
        
        while True:
            url = f"{self.url}/rest/api/2/search"
            query = {
                "jql": f"project = '{self.project_key}'",
                "fields": ["summary", "status", "description", "created", "updated"],
                "startAt": start_at,
                "maxResults": max_results
            }
            
            try:
                response = requests.get(url, headers=self.headers, params=query, timeout=30)
                if response.status_code != 200:
                    logger.error(f"Jira API error: {response.status_code} - {response.text}")
                    raise Exception(f"Failed to fetch tickets: {response.text}")
                
                data = response.json()
                issues = data.get("issues", [])
                if not issues:
                    break
                
                documents = []
                for issue in issues:
                    fields = issue.get("fields", {})
                    summary = fields.get("summary", "")
                    status = fields.get("status", {}).get("name", "Unknown")
                    description = fields.get("description") or "No description provided."
                    
                    # Constructing the TextSection including the missing description field
                    doc = Document(
                        id=f"jsm_ticket_{issue['id']}",
                        sections=[
                            TextSection(
                                text=(
                                    f"Summary: {summary}\n"
                                    f"Status: {status}\n"
                                    f"Description: {description}"
                                ),
                                link=f"{self.url}/browse/{issue['key']}"
                            )
                        ],
                        source=self.source,
                        semantic_identifier=issue.get("key", issue["id"]),
                        metadata={}
                    )
                    documents.append(doc)
                
                yield documents
                
                start_at += len(issues)
                if start_at >= data.get("total", 0):
                    break
                    
            except Exception as e:
                logger.error(f"Error executing Jira Service Management sync loop: {e}")
                raise e