"""
Jira Service Management (JSM) Connector for Onyx
Pulls tickets, incidents, and service requests from Jira Service Management projects.
Supports both Jira Cloud (/rest/api/3/search/jql with nextPageToken)
and Jira Server/Data Center (/rest/api/2/search with offset pagination).
"""

import logging
from typing import Any, Dict, List, Optional, Tuple, Union
import requests
from requests.auth import HTTPBasicAuth

logger = logging.getLogger(__name__)


class JiraApiError(Exception):
    """Raised when Jira Service Management API returns an error response."""

    def __init__(self, status_code: int, message: str, response_body: Optional[str] = None):
        super().__init__(f"Jira API error [HTTP {status_code}]: {message}")
        self.status_code = status_code
        self.response_body = response_body


class JiraServiceManagementConnector:
    """
    Connector to ingest service tickets and requests from Jira Service Management.
    Supports both Jira Cloud (Email + API Token) and Jira Server/Data Center (PAT/Bearer).
    """

    DEFAULT_TIMEOUT: Tuple[float, float] = (10.0, 30.0)
    DEFAULT_PAGE_SIZE: int = 50

    def __init__(
        self,
        jira_url: str,
        api_token: str,
        user_email: Optional[str] = None,
        timeout: Tuple[float, float] = DEFAULT_TIMEOUT,
    ):
        self.jira_url = jira_url.rstrip("/")
        self.api_token = api_token.strip()
        self.user_email = user_email.strip() if user_email else None
        self.timeout = timeout
        self.session = requests.Session()

    def _get_auth_and_headers(self) -> Tuple[Optional[HTTPBasicAuth], Dict[str, str]]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "Onyx-JSM-Connector/1.0",
        }
        if self.user_email:
            auth = HTTPBasicAuth(self.user_email, self.api_token)
            return auth, headers
        headers["Authorization"] = f"Bearer {self.api_token}"
        return None, headers

    def get_tickets(
        self,
        project_key: str,
        jql: Optional[str] = None,
        max_tickets: Optional[int] = None,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> List[Dict[str, Any]]:
        """
        Pull all tickets from a specified Jira Service Management project using pagination.

        Args:
            project_key: The Jira project key (e.g. 'IT', 'HELP', 'OPS').
            jql: Optional additional JQL filter expression.
            max_tickets: Maximum number of tickets to retrieve (None for all).
            page_size: Batch size per API query (default 50, max 100).

        Returns:
            List of parsed Jira ticket dictionaries.
        """
        if max_tickets is not None:
            if max_tickets < 0:
                raise ValueError("max_tickets cannot be negative")
            if max_tickets == 0:
                return []

        auth, headers = self._get_auth_and_headers()

        # Combine filter conditions first, then append a single final ORDER BY clause
        filter_clause = f"project = '{project_key}'"
        if jql:
            filter_clause = f"({filter_clause}) AND ({jql})"
        # Unique secondary sort by id DESC ensures deterministic pagination across nodes
        full_jql = f"{filter_clause} ORDER BY created DESC, id DESC"

        all_issues: List[Dict[str, Any]] = []
        limit = min(page_size, 100)

        # Jira Cloud uses /rest/api/3/search/jql with nextPageToken pagination
        # Jira Server/Data Center uses /rest/api/2/search with offset (startAt) pagination
        if self.user_email:
            endpoint = f"{self.jira_url}/rest/api/3/search/jql"
            next_page_token: Optional[str] = None

            while True:
                remaining = max_tickets - len(all_issues) if max_tickets is not None else limit
                page_limit = min(limit, remaining)
                if page_limit <= 0:
                    break

                params: Dict[str, Union[str, int]] = {
                    "jql": full_jql,
                    "maxResults": page_limit,
                }
                if next_page_token:
                    params["nextPageToken"] = next_page_token

                try:
                    response = self.session.get(
                        endpoint,
                        params=params,
                        headers=headers,
                        auth=auth,
                        timeout=self.timeout,
                    )
                except requests.RequestException as e:
                    logger.error(f"Network error querying Jira Cloud at {endpoint}: {e}")
                    raise JiraApiError(0, f"Network request failed: {e}") from e

                if response.status_code != 200:
                    raise JiraApiError(response.status_code, response.reason, response.text)

                data = response.json()
                issues = data.get("issues", [])
                if not issues:
                    break

                all_issues.extend(issues)

                if max_tickets is not None and len(all_issues) >= max_tickets:
                    all_issues = all_issues[:max_tickets]
                    break

                next_page_token = data.get("nextPageToken")
                if not next_page_token or data.get("isLast") is True:
                    break

            return all_issues

        # Server / Data Center flow (offset pagination)
        endpoint = f"{self.jira_url}/rest/api/2/search"
        start_at = 0

        while True:
            remaining = max_tickets - len(all_issues) if max_tickets is not None else limit
            page_limit = min(limit, remaining)
            if page_limit <= 0:
                break

            params_dc: Dict[str, Union[str, int]] = {
                "jql": full_jql,
                "startAt": start_at,
                "maxResults": page_limit,
                "fields": "*all",
            }

            try:
                response = self.session.get(
                    endpoint,
                    params=params_dc,
                    headers=headers,
                    auth=auth,
                    timeout=self.timeout,
                )
            except requests.RequestException as e:
                logger.error(f"Network error querying Jira Server/DC at {endpoint}: {e}")
                raise JiraApiError(0, f"Network request failed: {e}") from e

            if response.status_code != 200:
                raise JiraApiError(response.status_code, response.reason, response.text)

            data = response.json()
            issues = data.get("issues", [])
            if not issues:
                break

            all_issues.extend(issues)

            total = data.get("total")
            start_at += len(issues)

            if max_tickets is not None and len(all_issues) >= max_tickets:
                all_issues = all_issues[:max_tickets]
                break

            if total is not None and start_at >= total:
                break

        return all_issues
