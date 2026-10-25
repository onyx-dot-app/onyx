import time
from typing import Any
import requests
from requests.auth import HTTPBasicAuth

from onyx.utils.logger import setup_logger

logger = setup_logger()

_DEFAULT_TIMEOUT_SECONDS = 30
_MAX_RETRY_ATTEMPTS = 3
_BASE_BACKOFF_SECONDS = 2


class JsmApiError(Exception):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class JsmClient:
    def __init__(
        self,
        base_url: str,
        user_email: str | None = None,
        api_token: str | None = None,
        access_token: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "X-ExperimentalApi": "opt-in",
            }
        )

        if user_email and api_token:
            self.session.auth = HTTPBasicAuth(user_email, api_token)
        elif api_token:
            # Bearer token or PAT
            self.session.headers["Authorization"] = f"Bearer {api_token}"
        elif access_token:
            self.session.headers["Authorization"] = f"Bearer {access_token}"

    def _request(
        self, method: str, endpoint: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        url = f"{self.base_url}{endpoint}"
        last_exception: Exception | None = None

        for attempt in range(_MAX_RETRY_ATTEMPTS):
            try:
                response = self.session.request(
                    method=method,
                    url=url,
                    params=params,
                    timeout=_DEFAULT_TIMEOUT_SECONDS,
                )

                if response.status_code == 429:
                    last_exception = JsmApiError(
                        "Rate limited (429) by Atlassian Service Desk API",
                        status_code=429,
                    )
                    raw_retry_after = response.headers.get("Retry-After")
                    try:
                        retry_after = (
                            int(raw_retry_after)
                            if raw_retry_after
                            else _BASE_BACKOFF_SECONDS * (attempt + 1)
                        )
                    except (TypeError, ValueError):
                        retry_after = _BASE_BACKOFF_SECONDS * (attempt + 1)
                    retry_after = min(max(retry_after, 1), 60)
                    if attempt < _MAX_RETRY_ATTEMPTS - 1:
                        logger.warning(
                            "JSM rate limited (429). Retrying after %ss.",
                            retry_after,
                        )
                        time.sleep(retry_after)
                        continue
                    break

                if not response.ok:
                    raise JsmApiError(
                        f"JSM API error {response.status_code} on {endpoint}: {response.text}",
                        status_code=response.status_code,
                    )

                return response.json()
            except (requests.RequestException, JsmApiError) as e:
                last_exception = e
                if attempt < _MAX_RETRY_ATTEMPTS - 1:
                    sleep_time = _BASE_BACKOFF_SECONDS * (2**attempt)
                    time.sleep(sleep_time)
                else:
                    break

        raise JsmApiError(f"Failed JSM request after {_MAX_RETRY_ATTEMPTS} attempts: {last_exception}")

    def get_service_desks(self) -> list[dict[str, Any]]:
        endpoint = "/rest/servicedeskapi/servicedesk"
        start = 0
        service_desks: list[dict[str, Any]] = []

        while True:
            res = self._request(
                "GET", endpoint, params={"start": start, "limit": 50}
            )
            values = res.get("values", [])
            service_desks.extend(values)

            if not values or res.get("isLastPage", True):
                break
            start += len(values)

        return service_desks

    def get_customer_requests(
        self,
        service_desk_id: str | None = None,
        start: int = 0,
        limit: int = 50,
        request_status: str = "ALL_REQUESTS",
        search_term: str | None = None,
    ) -> dict[str, Any]:
        endpoint = "/rest/servicedeskapi/request"
        params: dict[str, Any] = {
            "start": start,
            "limit": limit,
            "requestStatus": request_status,
            "requestOwnership": "ALL_REQUESTS",
        }
        if service_desk_id:
            params["serviceDeskId"] = service_desk_id
        if search_term:
            params["searchTerm"] = search_term

        return self._request("GET", endpoint, params=params)

    def get_request_comments(
        self,
        issue_id_or_key: str,
        start: int = 0,
        limit: int = 50,
        public: bool | None = None,
    ) -> list[dict[str, Any]]:
        endpoint = f"/rest/servicedeskapi/request/{issue_id_or_key}/comment"
        comments: list[dict[str, Any]] = []
        next_start = start
        try:
            while True:
                params: dict[str, Any] = {
                    "start": next_start,
                    "limit": limit,
                }
                if public is not None:
                    params["public"] = str(public).lower()
                res = self._request("GET", endpoint, params=params)
                page = res.get("values", [])
                comments.extend(page)
                if res.get("isLastPage", True) or not page:
                    break
                next_start += len(page)
        except JsmApiError:
            raise
        return comments
