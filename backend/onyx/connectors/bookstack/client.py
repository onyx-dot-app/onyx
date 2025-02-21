from typing import Any

import requests


class BookStackClientRequestFailedError(ConnectionError):
    def __init__(self, status: int, error: str) -> None:
        self.status_code = status
        self.error = error
        super().__init__(
            "BookStack Client request failed with status {status}: {error}".format(
                status=status, error=error
            )
        )


class BookStackApiClient:
    def __init__(
        self,
        base_url: str,
        token_id: str,
        token_secret: str,
    ) -> None:
        self.base_url = base_url
        self.token_id = token_id
        self.token_secret = token_secret

    def get(self, endpoint: str, params: dict[str, str]) -> dict[str, Any]:
        url: str = self._build_url(endpoint)
        headers = self._build_headers()
        response = requests.get(url, headers=headers, params=params)

        try:
            json = response.json()
        except Exception:
            json = {}

        if response.status_code >= 300:
            error = response.reason
            response_error = json.get("error", {}).get("message", "")
            if response_error:
                error = response_error
            raise BookStackClientRequestFailedError(response.status_code, error)

        return json

    def _build_headers(self) -> dict[str, str]:
        auth = "Token " + self.token_id + ":" + self.token_secret
        return {
            "Authorization": auth,
            "Accept": "application/json",
        }

    def _build_url(self, endpoint: str) -> str:
        return self.base_url.rstrip("/") + "/api/" + endpoint.lstrip("/")

    def build_app_url(self, endpoint: str) -> str:
        return self.base_url.rstrip("/") + "/" + endpoint.lstrip("/")
