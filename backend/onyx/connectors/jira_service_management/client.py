"""Thin client for the Jira Service Management (JSM) REST API.

Cloud only for v1: authentication is Atlassian basic auth (account email +
API token), same as every other Atlassian cloud product.

Ref: https://developer.atlassian.com/cloud/jira/service-desk/rest/intro/
"""

from typing import Any

import requests
from requests.auth import HTTPBasicAuth
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import RequestException, Timeout

from onyx.configs.app_configs import REQUEST_TIMEOUT_SECONDS

# JSM list endpoints page with start/limit and answer with
# {start, limit, size, isLastPage, values}.
_PAGE_START = "start"
_PAGE_LIMIT = "limit"


class JsmClientRequestFailedError(ConnectionError):
    """Failed request to the JSM API, carrying the HTTP status."""

    def __init__(self, status: int, error: str) -> None:
        self.status_code = status
        self.error = error
        super().__init__(
            f"Jira Service Management request failed with status {status}: {error}"
        )


class JsmApiClient:
    """Minimal paging client for the JSM service-desk endpoints."""

    def __init__(self, base_url: str, email: str, api_token: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.auth = HTTPBasicAuth(email, api_token)

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.base_url}/rest/servicedeskapi/{path.lstrip('/')}"
        try:
            response = requests.get(
                url,
                auth=self.auth,
                params=params or {},
                headers={"Accept": "application/json"},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except Timeout:
            raise JsmClientRequestFailedError(
                408,
                "Request timed out - server did not respond within "
                f"{REQUEST_TIMEOUT_SECONDS} seconds",
            )
        except RequestsConnectionError as e:
            raise JsmClientRequestFailedError(
                -1, f"Connection error - unable to reach Jira: {e}"
            )
        except RequestException as e:
            raise JsmClientRequestFailedError(-1, f"Network error occurred: {e}")

        if response.status_code >= 300:
            error = response.reason or ""
            try:
                payload = response.json()
                # JSM errors arrive as {"errorMessage": ...} or
                # {"i18nErrorMessage": ...}; fall back to raw text.
                if isinstance(payload, dict):
                    error = (
                        payload.get("errorMessage")
                        or payload.get("i18nErrorMessage", {}).get("i18nErrorMessage")
                        or response.text.strip()
                        or error
                    )
            except Exception:
                if response.text.strip():
                    error = f"{response.reason}: {response.text.strip()}"
            raise JsmClientRequestFailedError(response.status_code, error)

        try:
            body = response.json()
        except Exception:
            raise JsmClientRequestFailedError(
                response.status_code,
                f"Response was successful but contained invalid JSON: {response.text}",
            )
        if not isinstance(body, dict):
            raise JsmClientRequestFailedError(
                response.status_code, f"Unexpected JSM response shape: {body!r}"
            )
        return body

    def iter_paged(
        self, path: str, page_size: int, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Collect every page of a JSM list endpoint into one list."""
        values: list[dict[str, Any]] = []
        start = 0
        while True:
            merged = dict(params or {})
            merged[_PAGE_START] = start
            merged[_PAGE_LIMIT] = page_size
            body = self.get(path, params=merged)
            page = body.get("values") or []
            if not isinstance(page, list):
                raise JsmClientRequestFailedError(
                    -1, f"JSM list endpoint returned non-list values: {body!r}"
                )
            values.extend(page)
            size = int(body.get("size", len(page)))
            if body.get("isLastPage", True) or size < page_size:
                break
            start += size
        return values

    def list_service_desks(self, page_size: int) -> list[dict[str, Any]]:
        return self.iter_paged("servicedesk", page_size)

    def list_request_types(
        self, service_desk_id: str, page_size: int
    ) -> list[dict[str, Any]]:
        return self.iter_paged(f"servicedesk/{service_desk_id}/requesttype", page_size)

    def list_requests(
        self, service_desk_id: str, page_size: int
    ) -> list[dict[str, Any]]:
        return self.iter_paged(f"servicedesk/{service_desk_id}/request", page_size)

    def list_request_comments(
        self, issue_id_or_key: str, page_size: int, public_only: bool = True
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if public_only:
            # Never index internal agent notes by default.
            params["public"] = "true"
        return self.iter_paged(
            f"request/{issue_id_or_key}/comment", page_size, params=params
        )

    def get_request(
        self, issue_id_or_key: str, expand: list[str] | None = None
    ) -> dict[str, Any]:
        params = {"expand": ",".join(expand)} if expand else None
        return self.get(f"request/{issue_id_or_key}", params=params)
