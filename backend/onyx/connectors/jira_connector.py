import base64
from collections.abc import Generator
from typing import Any
import requests

from onyx.connectors.interfaces import BaseConnector
from onyx.configs.constants import DocumentSource
from onyx.connectors.models import Document
from onyx.connectors.models import TextSection
from onyx.utils.logger import setup_logger

logger = setup_logger()

class JiraConnector(BaseConnector):
    def __init__(self, username: str, token: str, url: str, project_key: str):
        self.username = username
        self.token = token
        self.url = url.rstrip("/")
        self.project_key = project_key
        
        # Build encoded Basic Auth header correctly
        auth_str = f"{self.username}:{self.token}"
        encoded_auth = base64.b64encode(auth_str.encode("utf-8")).decode("utf-8")
        self.headers = {
            "Authorization": f"Basic {encoded_auth}",
            "Content-Type": "application/json"
        }

    @property
    def source(self) -> DocumentSource:
        return DocumentSource.JIRA_SERVICE_MANAGEMENT

    def load_credentials(self, credential_json: dict[str, Any]) -> None:
        # Implements required abstract method from BaseConnector
        pass

    def load_from_state(self) -> Generator[list[Document], None, None]:
        """Fetches all tickets from the specified Jira Service Management project using pagination."""
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
                    logger.error(f"Failed to fetch tickets from Jira: {response.status_code} - {response.text}")
                    break
                
                data = response.json()
                issues = data.get("issues", [])
                if not issues:
                    break
                
                documents = []
                for issue in issues:
                    fields = issue.get("fields", {})
                    summary = fields.get("summary", "")
                    status = fields.get("status", {}).get("name", "Unknown")
                    description = fields.get("description") or ""
                    
                    # Construct Document objects strictly adhering to Onyx models
                    doc = Document(
                        id=f"jsm_ticket_{issue['id']}",
                        sections=[
                            TextSection(
                                text=f"Summary: {summary}\nStatus: {status}\nDescription: {description}",
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
                total = data.get("total", 0)
                if start_at >= total:
                    break
                    
            except Exception as e:
                logger.error(f"Error executing Jira Service Management connector sync: {e}")
                break