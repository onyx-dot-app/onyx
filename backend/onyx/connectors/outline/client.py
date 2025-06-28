from typing import Any
from typing import Optional

import requests


class OutlineClientRequestFailedError(ConnectionError):
    def __init__(self, status: int, error: str) -> None:
        self.status_code = status
        self.error = error
        super().__init__(
            "Outline Client request failed with status {status}: {error}".format(
                status=status, error=error
            )
        )


class OutlineApiClient:
    def __init__(
        self,
        base_url: str,
        api_token: str,
    ) -> None:
        self.base_url = base_url
        self.api_token = api_token

    def post(
        self, endpoint: str, data: Optional[dict[str, Any]] = None
    ) -> dict[str, Any]:
        """Make a POST request to the Outline API (most endpoints use POST)"""
        url: str = self._build_url(endpoint)
        headers = self._build_headers()
        response = requests.post(url, headers=headers, json=data or {})

        try:
            json_response = response.json()
        except Exception:
            json_response = {}

        if response.status_code >= 300:
            error = response.reason
            response_error = json_response.get("error", {})
            if isinstance(response_error, dict):
                error = response_error.get("message", error)
            elif isinstance(response_error, str):
                error = response_error
            raise OutlineClientRequestFailedError(response.status_code, error)

        return json_response

    def get(
        self, endpoint: str, params: Optional[dict[str, str]] = None
    ) -> dict[str, Any]:
        """Make a GET request to the Outline API (few endpoints use GET)"""
        url: str = self._build_url(endpoint)
        headers = self._build_headers()
        response = requests.get(url, headers=headers, params=params or {})

        try:
            json_response = response.json()
        except Exception:
            json_response = {}

        if response.status_code >= 300:
            error = response.reason
            response_error = json_response.get("error", {})
            if isinstance(response_error, dict):
                error = response_error.get("message", error)
            elif isinstance(response_error, str):
                error = response_error
            raise OutlineClientRequestFailedError(response.status_code, error)

        return json_response

    def _build_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _build_url(self, endpoint: str) -> str:
        return self.base_url.rstrip("/") + "/api/" + endpoint.lstrip("/")

    def build_app_url(self, endpoint: str) -> str:
        return self.base_url.rstrip("/") + "/" + endpoint.lstrip("/")
