from typing import List, Dict, Any
import requests
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.models import Document, TextSection
from onyx.configs.constants import DocumentSource
from onyx.utils.logger import setup_logger

logger = setup_logger()

class JiraServiceManagementConnector(PollConnector):
    """
    Sovereign implementation for Jira Service Management.
    Handles paginated ticket indexing and secure credential loading.
    """
    
    def __init__(self, **kwargs: Any):
        self.username: str | None = None
        self.api_token: str | None = None
        self.url: str | None = None
        self.project_key: str | None = None

    def load_credentials(self, db_credentials: Dict[str, Any]) -> None:
        """Injects credentials from Onyx database into the connector instance."""
        self.username = db_credentials.get("username")
        self.api_token = db_credentials.get("api_token")
        self.url = db_credentials.get("url", "").rstrip("/")
        self.project_key = db_credentials.get("project_key")
        
        if not all([self.username, self.api_token, self.url, self.project_key]):
            logger.error("Jira JSM: Missing required credentials in db_credentials.")
            raise ValueError("Jira JSM: missing required credentials in db_credentials")
    def poll(self) -> List[Document]:
        """Entry point for the Onyx indexing pipeline."""
        all_docs = []
        start_at = 0
        max_results = 50
        
        if not self.project_key:
            logger.error("Jira JSM: No project key provided.")
            return []

        logger.info(f"Starting JSM poll for project: {self.project_key}")
        
        while True:
            try:
                data = self._fetch_tickets(start_at, max_results)
                issues = data.get("issues", [])
                if not issues:
                    break
                
                for issue in issues:
                    doc = self._map_issue_to_document(issue)
                    all_docs.append(doc)
                
                start_at += max_results
                if start_at >= data.get("total", 0):
                    break
            except Exception as e:
                logger.error(f"Failed to fetch JSM tickets at offset {start_at}: {e}")
                break
                
        return all_docs

    def _fetch_tickets(self, start_at: int, max_results: int) -> Dict[str, Any]:
        """Raw API call to Jira REST API v2 search endpoint."""
        url = f"{self.url}/rest/api/2/search"
        params = {
            "jql": f"project = {self.project_key}",
            "startAt": start_at,
            "maxResults": max_results,
            "fields": ["summary", "description", "updated", "created"]
        }
        response = requests.get(
            url, 
            auth=(self.username, self.api_token), 
            params=params,
            timeout=30
        )
        response.raise_for_status()
        return response.json()

    def _map_issue_to_document(self, issue: Dict[str, Any]) -> Document:
        """Converts a Jira JSON issue into a standard Onyx Document."""
        key = issue.get("key")
        fields = issue.get("fields", {})
        page_url = f"{self.url}/browse/{key}"
        
        return Document(
            id=page_url,
            sections=[
                TextSection(
                    link=page_url, 
                    text=fields.get("description") or "No description provided."
                )
            ],
            source=DocumentSource.JIRA,
            semantic_identifier=f"{key}: {fields.get('summary')}",
            title=f"[{key}] {fields.get('summary')}",
            metadata={
                "project": self.project_key,
                "issue_key": key,
                "status": fields.get("status", {}).get("name") if isinstance(fields.get("status"), dict) else "Unknown"
            }
        )