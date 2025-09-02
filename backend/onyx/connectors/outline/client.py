from typing import Any

import requests
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import RequestException
from requests.exceptions import Timeout

from onyx.configs.app_configs import REQUEST_TIMEOUT_SECONDS


class OutlineClientRequestFailedError(ConnectionError):
    """Custom error class for handling failed requests to the Outline API with status code and error message"""

    def __init__(self, status: int, error: str) -> None:
        self.status_code = status
        self.error = error
        super().__init__(f"Outline Client request failed with status {status}: {error}")


class OutlineApiClient:
    """Client for interacting with the Outline API. Handles authentication and making HTTP requests."""

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
            response = requests.post(
                url, headers=headers, json=data, timeout=REQUEST_TIMEOUT_SECONDS
            )
        except Timeout:
            raise OutlineClientRequestFailedError(
                408,
                f"Request timed out - server did not respond within {REQUEST_TIMEOUT_SECONDS} seconds",
            )
        except RequestsConnectionError as e:
            raise OutlineClientRequestFailedError(
                -1, f"Connection error - unable to reach Outline server: {e}"
            )
        except RequestException as e:
            raise OutlineClientRequestFailedError(-1, f"Network error occurred: {e}")

        if response.status_code >= 300:
            error = response.reason
            try:
                response_json = response.json()
                if isinstance(response_json, dict):
                    response_error = response_json.get("error", {}).get("message", "")
                    if response_error:
                        error = response_error
            except Exception:
                # If JSON parsing fails, fall back to response.text for better debugging
                if response.text.strip():
                    error = f"{response.reason}: {response.text.strip()}"
            raise OutlineClientRequestFailedError(response.status_code, error)

        try:
            return response.json()
        except Exception:
            raise OutlineClientRequestFailedError(
                response.status_code,
                f"Response was successful but contained invalid JSON: {response.text}",
            )

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
