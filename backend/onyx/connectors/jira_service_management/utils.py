"""Utility functions for Jira Service Management connector."""

from __future__ import annotations

import time
from typing import Any

import httpx

from onyx.utils.logger import setup_logger

logger = setup_logger()

# Jira API constraints
JSM_MAX_PAGE_SIZE = 100
JSM_DEFAULT_PAGE_SIZE = 50
JSM_RATE_LIMIT_RETRY_ATTEMPTS = 3
JSM_RATE_LIMIT_INITIAL_BACKOFF = 1.0  # seconds


class JSMRateLimitError(Exception):
    """Raised when Jira API rate limit is hit."""


class JSMAuthError(Exception):
    """Raised when Jira API authentication fails."""


class JSMAPIError(Exception):
    """General Jira API error."""


class JSMPaginatedClient:
    """Wrapper around httpx for paginated Jira Service Management API calls."""

    def __init__(
        self,
        jira_base_url: str,
        email: str | None = None,
        api_token: str | None = None,
        personal_token: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.jira_base_url = jira_base_url.rstrip("/")
        self.timeout = timeout

        if email and api_token:
            # Basic Auth (Cloud or Server with username/password)
            self.auth = (email, api_token)
            self.headers: dict[str, str] = {}
        elif personal_token:
            # Personal Access Token / Bearer Auth (Server/Data Center)
            self.auth = None
            self.headers = {"Authorization": f"Bearer {personal_token}"}
        else:
            raise JSMAuthError(
                "Either (email + api_token) or personal_token must be provided."
            )

        self._client = httpx.Client(
            base_url=self.jira_base_url,
            auth=self.auth,
            headers=self.headers,
            timeout=httpx.Timeout(timeout),
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> JSMPaginatedClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def _request_with_retry(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
    ) -> httpx.Response:
        """Make an HTTP request with rate-limit retry logic."""
        url = f"{self.jira_base_url}/rest/api/2{path}"
        backoff = JSM_RATE_LIMIT_INITIAL_BACKOFF

        for attempt in range(JSM_RATE_LIMIT_RETRY_ATTEMPTS):
            response = self._client.request(
                method=method,
                url=url,
                params=params,
                json=json_data,
            )

            if response.status_code == 429:
                retry_after = float(response.headers.get("Retry-After", backoff))
                logger.warning(
                    f"JSM API rate limit hit. Retrying in {retry_after}s "
                    f"(attempt {attempt + 1}/{JSM_RATE_LIMIT_RETRY_ATTEMPTS})."
                )
                time.sleep(retry_after)
                backoff *= 2
                continue

            if response.status_code == 401:
                raise JSMAuthError("Authentication failed (HTTP 401). Check credentials.")

            if response.status_code == 403:
                raise JSMAPIError(
                    f"Insufficient permissions (HTTP 403). Path: {path}"
                )

            if response.status_code >= 400:
                raise JSMAPIError(
                    f"JSM API error: HTTP {response.status_code} - "
                    f"{response.text[:500]} for path {path}"
                )

            return response

        raise JSMRateLimitError(
            f"JSM API rate limit exceeded after {JSM_RATE_LIMIT_RETRY_ATTEMPTS} attempts."
        )

    def _service_desk_request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
    ) -> httpx.Response:
        """Make a request to the Jira Service Management REST API (under /rest/servicedeskapi/)."""
        url = f"{self.jira_base_url}/rest/servicedeskapi{path}"
        backoff = JSM_RATE_LIMIT_INITIAL_BACKOFF

        for attempt in range(JSM_RATE_LIMIT_RETRY_ATTEMPTS):
            response = self._client.request(
                method=method,
                url=url,
                params=params,
                json=json_data,
            )

            if response.status_code == 429:
                retry_after = float(response.headers.get("Retry-After", backoff))
                logger.warning(
                    f"JSM Service Desk API rate limit hit. Retrying in {retry_after}s "
                    f"(attempt {attempt + 1}/{JSM_RATE_LIMIT_RETRY_ATTEMPTS})."
                )
                time.sleep(retry_after)
                backoff *= 2
                continue

            if response.status_code == 401:
                raise JSMAuthError("Authentication failed (HTTP 401). Check credentials.")

            if response.status_code == 403:
                raise JSMAPIError(
                    f"Insufficient permissions for Service Desk API (HTTP 403). Path: {path}"
                )

            if response.status_code >= 400:
                raise JSMAPIError(
                    f"JSM Service Desk API error: HTTP {response.status_code} - "
                    f"{response.text[:500]} for path {path}"
                )

            return response

        raise JSMRateLimitError(
            f"JSM Service Desk API rate limit exceeded after {JSM_RATE_LIMIT_RETRY_ATTEMPTS} attempts."
        )

    def paginated_get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        page_size: int = JSM_DEFAULT_PAGE_SIZE,
        use_servicedesk_api: bool = False,
    ) -> list[dict[str, Any]]:
        """Fetch all pages of a paginated GET endpoint.

        Supports both Jira REST API (/rest/api/2/) and
        Service Desk REST API (/rest/servicedeskapi/) pagination.

        Jira REST API pagination uses `startAt` and `maxResults`.
        Service Desk API pagination uses `start` and `limit` with
        `_links.next` for cursor-based pagination.
        """
        if params is None:
            params = {}

        request_fn = self._service_desk_request if use_servicedesk_api else self._request_with_retry

        if use_servicedesk_api:
            # Service Desk API uses cursor-based pagination
            params["limit"] = min(page_size, JSM_MAX_PAGE_SIZE)
            all_items: list[dict[str, Any]] = []

            while True:
                response = request_fn("GET", path, params=params)
                data = response.json()
                all_items.extend(data.get("values", []))

                if not data.get("values"):
                    break

                next_page = data.get("_links", {}).get("next")
                if not next_page:
                    break

                # Reset params for next page (URL is fully qualified in _links.next)
                params = {}

            return all_items
        else:
            # Standard Jira REST API pagination
            start_at = 0
            all_items = []
            params["maxResults"] = min(page_size, JSM_MAX_PAGE_SIZE)

            while True:
                params["startAt"] = start_at
                response = request_fn("GET", path, params=params)
                data = response.json()
                issues = data.get("issues", data.get("values", []))
                if not issues:
                    break
                all_items.extend(issues)

                total = data.get("total", 0)
                if start_at + len(issues) >= total:
                    break
                start_at += len(issues)

            return all_items

    def get_service_desks(self) -> list[dict[str, Any]]:
        """Get all accessible service desks."""
        return self.paginated_get(
            "/servicedesk",
            use_servicedesk_api=True,
        )

    def get_service_desk_info(self, service_desk_id: str) -> dict[str, Any]:
        """Get info about a specific service desk."""
        response = self._service_desk_request("GET", f"/servicedesk/{service_desk_id}")
        return response.json()

    def search_tickets(
        self,
        jql: str,
        fields: str | None = None,
        page_size: int = JSM_DEFAULT_PAGE_SIZE,
    ) -> list[dict[str, Any]]:
        """Search JSM tickets using JQL via the standard Jira REST API."""
        params: dict[str, Any] = {
            "jql": jql,
            "maxResults": min(page_size, JSM_MAX_PAGE_SIZE),
        }
        if fields:
            params["fields"] = fields

        start_at = 0
        all_issues: list[dict[str, Any]] = []

        while True:
            params["startAt"] = start_at
            response = self._request_with_retry("GET", "/search", params=params)
            data = response.json()
            issues = data.get("issues", [])
            if not issues:
                break
            all_issues.extend(issues)

            total = data.get("total", 0)
            if start_at + len(issues) >= total:
                break
            start_at += len(issues)

        return all_issues

    def search_tickets_paged(
        self,
        jql: str,
        fields: str | None = None,
        page_size: int = JSM_DEFAULT_PAGE_SIZE,
        start_at: int = 0,
    ) -> tuple[list[dict[str, Any]], bool]:
        """Search JSM tickets with pagination. Returns (issues, has_more)."""
        params: dict[str, Any] = {
            "jql": jql,
            "maxResults": min(page_size, JSM_MAX_PAGE_SIZE),
            "startAt": start_at,
        }
        if fields:
            params["fields"] = fields

        response = self._request_with_retry("GET", "/search", params=params)
        data = response.json()
        issues = data.get("issues", [])
        total = data.get("total", 0)
        has_more = (start_at + len(issues)) < total
        return issues, has_more

    def get_ticket_comments(self, issue_key: str) -> list[dict[str, Any]]:
        """Get comments for a specific ticket."""
        return self.paginated_get(f"/issue/{issue_key}/comment")

    def get_ticket_attachments(self, issue_key: str) -> list[dict[str, Any]]:
        """Get attachment metadata for a specific ticket."""
        response = self._request_with_retry("GET", f"/issue/{issue_key}")
        fields = response.json().get("fields", {})
        return fields.get("attachment", [])
