import requests
from typing import Any
from onyx.utils.logger import setup_logger

logger = setup_logger()

class JSMClient:
    def __init__(self, jira_base_url: str, credentials: dict[str, Any]):
        self.jira_base_url = jira_base_url.rstrip("/")
        self.api_url = f"{self.jira_base_url}/rest/servicedeskapi"
        self.session = requests.Session()
        
        api_token = credentials.get("jira_api_token")
        email = credentials.get("jira_user_email")
        
        if email and api_token:
            self.session.auth = (email, api_token)
        elif api_token:
            # Assume personal access token or similar
            self.session.headers.update({"Authorization": f"Bearer {api_token}"})

    def get_service_desk_id(self, project_key: str) -> str | None:
        url = f"{self.api_url}/servicedesk"
        # Iterate through pages to find the service desk
        start = 0
        limit = 50
        while True:
            params = {"start": start, "limit": limit}
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            service_desks = data.get("values", [])
            
            for sd in service_desks:
                if sd.get("projectKey") == project_key:
                    return str(sd.get("id"))
            
            if data.get("isLastPage", True):
                break
            start += limit
            
        return None

    def get_requests(self, service_desk_id: str | None = None, start: int = 0, limit: int = 50) -> dict[str, Any]:
        url = f"{self.api_url}/request"
        params: dict[str, Any] = {"start": start, "limit": limit}
        if service_desk_id:
            params["serviceDeskId"] = service_desk_id
        
        response = self.session.get(url, params=params)
        response.raise_for_status()
        return response.json()

    def get_request_details(self, request_id_or_key: str) -> dict[str, Any]:
        url = f"{self.api_url}/request/{request_id_or_key}"
        response = self.session.get(url)
        response.raise_for_status()
        return response.json()

    def get_comments(self, request_id_or_key: str, start: int = 0, limit: int = 50) -> dict[str, Any]:
        url = f"{self.api_url}/request/{request_id_or_key}/comment"
        params = {"start": start, "limit": limit}
        response = self.session.get(url, params=params)
        response.raise_for_status()
        return response.json()
