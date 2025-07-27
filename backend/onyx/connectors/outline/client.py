from typing import Any

import requests


class OutlineClientRequestFailedError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        self.message = message
        super().__init__(f"Outline API request failed with status {status_code}: {message}")


class OutlineApiClient:
    def __init__(
        self,
        base_url: str,
        api_token: str,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token

    def post(self, endpoint: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        """Make a POST request to the Outline API"""
        url = self._build_url(endpoint)
        headers = self._build_headers()
        
        response = requests.post(url, headers=headers, json=data or {})

        try:
            json_response = response.json()
        except Exception:
            json_response = {}

        if response.status_code >= 300:
            error_message = response.reason
            if json_response.get("error"):
                error_message = json_response["error"]
            elif json_response.get("message"):
                error_message = json_response["message"]
            raise OutlineClientRequestFailedError(response.status_code, error_message)

        return json_response

    def _build_headers(self) -> dict[str, str]:
        """Build headers for API requests"""
        return {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _build_url(self, endpoint: str) -> str:
        """Build the full URL for an API endpoint"""
        return f"{self.base_url}/api/{endpoint.lstrip('/')}"

    def build_app_url(self, path: str) -> str:
        """Build a URL for the Outline application (for document links)"""
        return f"{self.base_url}/{path.lstrip('/')}"
