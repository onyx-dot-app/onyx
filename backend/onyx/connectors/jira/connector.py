from typing import List, Dict, Any
import requests
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.models import Document

class JiraServiceManagementConnector(PollConnector):
    def load_credentials(self, db_credentials: Dict[str, Any]):
        self.username = db_credentials.get('username')
        self.api_token = db_credentials.get('api_token')
        self.url = db_credentials.get('url')
        self.project_key = db_credentials.get('project_key')

    def poll(self) -> List[Document]:
        tickets = []
        start_at = 0
        max_results = 50
        while True:
            response = self._fetch_tickets(start_at, max_results)
            issues = response.get('issues', [])
            if not issues:
                break
            for issue in issues:
                doc = Document(
                    id=issue['key'],
                    title=issue['fields'].get('summary', ''),
                    content=issue['fields'].get('description', '') or ''
                )
                tickets.append(doc)
            start_at += max_results
        return tickets

    def _fetch_tickets(self, start_at: int, max_results: int) -> Dict[str, Any]:
        url = f"{self.url}/rest/api/2/search"
        params = {
            "jql": f"project = {self.project_key}",
            "startAt": start_at,
            "maxResults": max_results,
            "fields": ["summary", "description"]
        }
        response = requests.get(
            url, 
            auth=(self.username, self.api_token), 
            params=params
        )
        response.raise_for_status()
        return response.json()
