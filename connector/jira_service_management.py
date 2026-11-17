```python
import requests
from typing import List, Dict

class JiraServiceManagementConnector:
    def __init__(self, jira_url: str, api_token: str):
        self.jira_url = jira_url
        self.api_token = api_token

    def get_tickets(self, project_key: str) -> List[Dict[str, str]]:
        headers = {
            'Authorization': f'Bearer {self.api_token}',
            'Content-Type': 'application/json'
        }

        response = requests.get(f'{self.jira_url}/rest/api/3/search', params={'jql': f'project={project_key}'}, headers=headers)

        if response.status_code == 200:
            return response.json().get('issues', [])
        else:
            raise Exception(f'Failed to fetch tickets: {response.status_code} - {response.text}')
```
