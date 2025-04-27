from typing import Any

import requests

import random
import time

RETRYABLE_STATUSES = {502, 503, 504}


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
        max_retries: int = 5,
        backoff_factor: float = 2.0,
    ) -> None:
        self.base_url = base_url
        self.token_id = token_id
        self.token_secret = token_secret
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor

    def get(self, endpoint: str, params: dict[str, str]) -> dict[str, Any]:
        url: str = self._build_url(endpoint)
        headers = self._build_headers()
        retries = 0
        while retries  <= self.max_retries:
            try: 
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
            except BookStackClientRequestFailedError as e:
                if e.status_code not in RETRYABLE_STATUSES:
                    raise e
                retries += 1
                if retries > self.max_retries:
                    raise
                sleep_time = self.backoff_factor * (2 ** (retries - 1)) + random.uniform(0, 1)
                time.sleep(sleep_time)
            except requests.RequestException as e:
                retries += 1
                print(retries)
                if retries > self.max_retries:
                    raise BookStackClientRequestFailedError(503, str(e))
                sleep_time = self.backoff_factor * (2 ** (retries - 1)) + random.uniform(0, 1)
                time.sleep(sleep_time)

        raise BookStackClientRequestFailedError(500, "Maximum retries exceeded with no successful response")

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