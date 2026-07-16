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
        self.url = ""
        self.project_key = ""
        self.headers: dict[str, str] = {}

    def load_credentials(self, credential_json: dict[str, Any]) -> None:
        """Extracts credentials and rebuilds the Base64 Auth header."""
        username = credential_json.get("username")
        token = credential_json.get("token")
        self.url = credential_json.get("url", "").rstrip("/")
        self.project_key = credential_json.get("project_key", "")
        
        if not username or not token:
            logger.error("Missing Jira credentials.")
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
        """Fetches all tickets using pagination and yields Onyx Documents."""
        if not self.url or not self.project_key:
            return

        start_at = 0
        max_results = 50
        while True:
            url = f"{self.url}/rest/api/2/search"
            query: dict[str, Any] = {
                "jql": f"project = '{self.project_key}'",
                "fields": ["summary", "status", "description"],
                "startAt": start_at,
                "maxResults": max_results
            }
            
            response = requests.get(url, headers=self.headers, params=query, timeout=30)
            if response.status_code != 200:
                logger.error(f"Jira API Error: {response.text}")
                raise Exception(f"Sync failed with status {response.status_code}")
            
            data = response.json()
            issues = data.get("issues", [])
            if not issues:
                break
            
            documents = [
                Document(
                    id=f"jsm_ticket_{issue['id']}",
                    sections=[
                        TextSection(
                            text=f"Summary: {issue['fields'].get('summary')}\nDescription: {issue['fields'].get('description') or ''}",
                            link=f"{self.url}/browse/{issue['key']}"
                        )
                    ],
                    source=self.source,
                    semantic_identifier=issue.get("key", issue["id"]),
                    metadata={}
                ) for issue in issues
            ]
            yield documents
            
            start_at += len(issues)
            if start_at >= data.get("total", 0):
                break