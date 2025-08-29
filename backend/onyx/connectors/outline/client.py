import json
from typing import Any

import requests
from requests.exceptions import RequestException
from requests.exceptions import Timeout
from requests.exceptions import ConnectionError as RequestsConnectionError


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
        api_token: str,
        base_url: str,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token

    def post(self, endpoint: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        if data is None:
            data = {}
        url: str = self._build_url(endpoint)
        headers = self._build_headers()
        
        try:
            response = requests.post(url, headers=headers, json=data, timeout=60)
        except Timeout:
            raise OutlineClientRequestFailedError(
                408, "Request timed out - server did not respond within 60 seconds"
            )
        except RequestsConnectionError as e:
            raise OutlineClientRequestFailedError(
                -1, f"Connection error - unable to reach Outline server: {e}"
            )
        except RequestException as e:
            raise OutlineClientRequestFailedError(
                -1, f"Network error occurred: {e}"
            )

        try:
            response_json = response.json()
        except (ValueError, json.JSONDecodeError) as e:
            raise OutlineClientRequestFailedError(
                response.status_code, 
                f"Invalid JSON response: {e}"
            ) from e

        if response.status_code >= 300:
            error = response.reason
            response_error = response_json.get("error", {}).get("message", "")
            if response_error:
                error = response_error
            raise OutlineClientRequestFailedError(response.status_code, error)

        return response_json

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
