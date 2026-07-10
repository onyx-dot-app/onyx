import requests
import json

class JiraConnector:
    def __init__(self, base_url, api_token, project_key):
        self.base_url = base_url
        self.api_token = api_token
        self.project_key = project_key

    def get_tickets(self):
        headers = {
            'Authorization': f'Bearer {self.api_token}',
            'Content-Type': 'application/json'
        }
        url = f'{self.base_url}/rest/api/3/search?jql=project={self.project_key}'
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.json()['issues']
        else:
            return None
