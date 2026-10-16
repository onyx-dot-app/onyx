from collections.abc import Iterator
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from onyx.connectors.cross_connector_utils.miscellaneous_utils import scoped_url
from onyx.utils.logger import setup_logger

logger = setup_logger()

DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_PAGE_SIZE = 50
MAX_JSM_PAGE_SIZE = 100


class JiraServiceManagementClientError(Exception):
    """Raised when the Jira Service Management or Jira REST API returns an error."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        response_text: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_text = response_text


class JiraServiceManagementClient:
    """HTTP client for Jira Service Management REST API (/rest/servicedeskapi/*)
    and Jira Platform REST API (/rest/api/2/* or /rest/api/3/*).

    Supports both:
    - Jira Service Management Cloud (Basic Auth with email + API token, or scoped token)
    - Jira Service Management Data Center / Server (Personal Access Token via Bearer Auth,
      or Basic Auth with username + password/token)
    """

    def __init__(
        self,
        base_url: str,
        api_token: str,
        user_email: str | None = None,
        scoped_token: bool = False,
        api_version: str | None = None,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
        session: requests.Session | None = None,
    ) -> None:
        raw_base = base_url.rstrip("/")
        if scoped_token:
            resolved_url = scoped_url(raw_base, "jira")
            self.base_url = (resolved_url or raw_base).rstrip("/")
        else:
            self.base_url = raw_base

        self.original_base_url = raw_base
        self.api_token = api_token
        self.user_email = user_email
        self.scoped_token = scoped_token
        self.timeout = timeout

        # Auto-detect API version if not explicitly specified:
        # Cloud instances (*.atlassian.net or api.atlassian.com) default to v3,
        # self-hosted Data Center / Server instances default to v2.
        if api_version:
            self.api_version = str(api_version).strip()
        elif (
            "atlassian.net" in self.base_url.lower()
            or "atlassian.com" in self.base_url.lower()
        ):
            self.api_version = "3"
        else:
            self.api_version = "2"

        self.session = session or self._build_session()

    def _build_session(self) -> requests.Session:
        session = requests.Session()
        retry_strategy = Retry(
            total=4,
            backoff_factor=1.0,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "POST", "OPTIONS"],
            respect_retry_after_header=True,
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("https://", adapter)
        session.mount("http://", adapter)

        headers: dict[str, str] = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            # Required by certain JSM experimental endpoints (e.g. SLA/request types/organizations)
            "X-ExperimentalApi": "opt-in",
        }
        if self.user_email:
            session.auth = (self.user_email, self.api_token)
        else:
            headers["Authorization"] = f"Bearer {self.api_token}"

        session.headers.update(headers)
        return session

    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
        stream: bool = False,
    ) -> requests.Response:
        url = path if path.startswith("http") else f"{self.base_url}/{path.lstrip('/')}"
        try:
            response = self.session.request(
                method=method,
                url=url,
                params=params,
                json=json_body,
                headers=extra_headers,
                timeout=self.timeout,
                stream=stream,
            )
        except requests.RequestException as exc:
            raise JiraServiceManagementClientError(
                f"Failed to connect to Jira Service Management at {url}: {exc}"
            ) from exc

        if response.status_code >= 400:
            error_msg = self._extract_error_message(response)
            raise JiraServiceManagementClientError(
                f"JSM API error ({response.status_code}) for {method} {path}: {error_msg}",
                status_code=response.status_code,
                response_text=response.text,
            )

        return response

    def _get_json(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        resp = self._request("GET", path, params=params, extra_headers=extra_headers)
        if not resp.content:
            return {}
        data = resp.json()
        return data if isinstance(data, dict) else {"values": data}

    def _post_json(
        self,
        path: str,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        resp = self._request(
            "POST",
            path,
            params=params,
            json_body=json_body,
            extra_headers=extra_headers,
        )
        if not resp.content:
            return {}
        data = resp.json()
        return data if isinstance(data, dict) else {"values": data}

    @staticmethod
    def _extract_error_message(response: requests.Response) -> str:
        try:
            payload = response.json()
            if isinstance(payload, dict):
                error_messages = payload.get("errorMessages")
                if isinstance(error_messages, list) and error_messages:
                    return "; ".join(str(m) for m in error_messages)
                errors = payload.get("errors")
                if isinstance(errors, dict) and errors:
                    return "; ".join(f"{k}: {v}" for k, v in errors.items())
                if "message" in payload:
                    return str(payload["message"])
                if "errorMessage" in payload:
                    return str(payload["errorMessage"])
        except Exception:
            pass
        return (response.text or response.reason or "Unknown HTTP error")[:500]

    def paginate_servicedesk_api(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> Iterator[dict[str, Any]]:
        """Iterate through a JSM REST API endpoint that uses start/limit/size/isLastPage/values."""
        start = 0
        page_limit = min(max(1, limit), MAX_JSM_PAGE_SIZE)
        base_params = dict(params or {})

        while True:
            query_params = {
                **base_params,
                "start": start,
                "limit": page_limit,
            }
            data = self._get_json(path, params=query_params)
            values = data.get("values")
            if not isinstance(values, list) or not values:
                break

            for item in values:
                if isinstance(item, dict):
                    yield item

            is_last_page = data.get("isLastPage")
            size = data.get("size", len(values))
            if is_last_page is True or size == 0 or len(values) < page_limit:
                # Note: Some JSM endpoints set isLastPage=False until an empty page or explicitly True
                if is_last_page is True or size == 0:
                    break

            start += len(values)

    # -------------------------------------------------------------------------
    # Service Desk & Queue Discovery
    # -------------------------------------------------------------------------

    def get_service_desk_info(self) -> dict[str, Any]:
        """GET /rest/servicedeskapi/info - Verify JSM API connectivity and version info."""
        return self._get_json("/rest/servicedeskapi/info")

    def get_myself(self) -> dict[str, Any]:
        """GET /rest/api/{version}/myself - Verify Jira platform credentials."""
        return self._get_json(f"/rest/api/{self.api_version}/myself")

    def list_service_desks(self) -> list[dict[str, Any]]:
        """GET /rest/servicedeskapi/servicedesk - List all accessible service desks."""
        return list(self.paginate_servicedesk_api("/rest/servicedeskapi/servicedesk"))

    def get_service_desk(self, service_desk_id: str) -> dict[str, Any]:
        """GET /rest/servicedeskapi/servicedesk/{serviceDeskId}."""
        return self._get_json(f"/rest/servicedeskapi/servicedesk/{service_desk_id}")

    def list_queues(
        self,
        service_desk_id: str,
        include_count: bool = False,
    ) -> list[dict[str, Any]]:
        """GET /rest/servicedeskapi/servicedesk/{serviceDeskId}/queue."""
        params: dict[str, Any] = {"includeCount": "true" if include_count else "false"}
        return list(
            self.paginate_servicedesk_api(
                f"/rest/servicedeskapi/servicedesk/{service_desk_id}/queue",
                params=params,
            )
        )

    def iter_queue_issues(
        self,
        service_desk_id: str,
        queue_id: str,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> Iterator[dict[str, Any]]:
        """GET /rest/servicedeskapi/servicedesk/{serviceDeskId}/queue/{queueId}/issue."""
        yield from self.paginate_servicedesk_api(
            f"/rest/servicedeskapi/servicedesk/{service_desk_id}/queue/{queue_id}/issue",
            limit=limit,
        )

    # -------------------------------------------------------------------------
    # Customer Requests, SLA, Comments, Attachments
    # -------------------------------------------------------------------------

    def iter_customer_requests(
        self,
        service_desk_id: str | None = None,
        request_type_id: str | None = None,
        search_term: str | None = None,
        expand: list[str] | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> Iterator[dict[str, Any]]:
        """GET /rest/servicedeskapi/request."""
        params: dict[str, Any] = {}
        if service_desk_id:
            params["serviceDeskId"] = service_desk_id
        if request_type_id:
            params["requestTypeId"] = request_type_id
        if search_term:
            params["searchTerm"] = search_term
        if expand:
            params["expand"] = ",".join(expand)
        yield from self.paginate_servicedesk_api(
            "/rest/servicedeskapi/request",
            params=params,
            limit=limit,
        )

    def get_customer_request(
        self,
        issue_id_or_key: str,
        expand: list[str] | None = None,
    ) -> dict[str, Any]:
        """GET /rest/servicedeskapi/request/{issueIdOrKey}."""
        params: dict[str, Any] = {}
        if expand:
            params["expand"] = ",".join(expand)
        return self._get_json(
            f"/rest/servicedeskapi/request/{issue_id_or_key}",
            params=params,
        )

    def get_request_sla(
        self,
        issue_id_or_key: str,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> list[dict[str, Any]]:
        """GET /rest/servicedeskapi/request/{issueIdOrKey}/sla."""
        return list(
            self.paginate_servicedesk_api(
                f"/rest/servicedeskapi/request/{issue_id_or_key}/sla",
                limit=limit,
            )
        )

    def get_request_comments(
        self,
        issue_id_or_key: str,
        public: bool = True,
        internal: bool = True,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> list[dict[str, Any]]:
        """GET /rest/servicedeskapi/request/{issueIdOrKey}/comment."""
        params: dict[str, Any] = {
            "public": "true" if public else "false",
            "internal": "true" if internal else "false",
            "expand": "renderedBody,attachment",
        }
        return list(
            self.paginate_servicedesk_api(
                f"/rest/servicedeskapi/request/{issue_id_or_key}/comment",
                params=params,
                limit=limit,
            )
        )

    def get_request_attachments(
        self,
        issue_id_or_key: str,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> list[dict[str, Any]]:
        """GET /rest/servicedeskapi/request/{issueIdOrKey}/attachment."""
        return list(
            self.paginate_servicedesk_api(
                f"/rest/servicedeskapi/request/{issue_id_or_key}/attachment",
                limit=limit,
            )
        )

    def download_attachment(
        self,
        content_url: str,
        max_size_bytes: int | None = None,
    ) -> bytes | None:
        """Download raw bytes for an attachment URL, enforcing an optional size cap."""
        if not content_url:
            return None
        try:
            resp = self._request(
                "GET",
                content_url,
                extra_headers={"Accept": "*/*"},
                stream=True,
            )
            chunks: list[bytes] = []
            total = 0
            for chunk in resp.iter_content(chunk_size=65536):
                if not chunk:
                    continue
                total += len(chunk)
                if max_size_bytes is not None and total > max_size_bytes:
                    logger.debug(
                        f"Skipping attachment {content_url}: exceeded max size {max_size_bytes} bytes"
                    )
                    resp.close()
                    return None
                chunks.append(chunk)
            return b"".join(chunks)
        except Exception as exc:
            logger.warning(f"Failed to download JSM attachment from {content_url}: {exc}")
            return None

    # -------------------------------------------------------------------------
    # Jira Platform REST API (JQL Search, Issue Details, Changelogs)
    # -------------------------------------------------------------------------

    def get_issue(
        self,
        issue_id_or_key: str,
        fields: str = "*all",
        expand: str | None = "renderedFields,names",
    ) -> dict[str, Any]:
        """GET /rest/api/{version}/issue/{issueIdOrKey}."""
        params: dict[str, Any] = {"fields": fields}
        if expand:
            params["expand"] = expand
        return self._get_json(
            f"/rest/api/{self.api_version}/issue/{issue_id_or_key}",
            params=params,
        )

    def get_issue_changelog(
        self,
        issue_id_or_key: str,
        max_results: int = 100,
    ) -> list[dict[str, Any]]:
        """Fetch changelog entries for an issue.

        Uses /rest/api/{version}/issue/{issueIdOrKey}/changelog on Cloud/v3,
        falling back to GET /rest/api/{version}/issue/{issueIdOrKey}?expand=changelog
        if the dedicated changelog endpoint is unavailable (e.g. older Jira Server).
        """
        histories: list[dict[str, Any]] = []
        start_at = 0

        try:
            while True:
                data = self._get_json(
                    f"/rest/api/{self.api_version}/issue/{issue_id_or_key}/changelog",
                    params={"startAt": start_at, "maxResults": max_results},
                )
                values = data.get("values")
                if not isinstance(values, list):
                    # Some versions return {"changelog": {"histories": [...]}} or {"histories": [...]}
                    values = data.get("histories")
                if not isinstance(values, list) or not values:
                    break

                for item in values:
                    if isinstance(item, dict):
                        histories.append(item)

                is_last = data.get("isLast")
                total = data.get("total")
                start_at += len(values)
                if is_last is True:
                    break
                if isinstance(total, int) and start_at >= total:
                    break
                if len(values) < max_results:
                    break
            return histories
        except JiraServiceManagementClientError as exc:
            if exc.status_code not in (400, 404, 405):
                raise
            # Fallback to issue expand=changelog
            issue_data = self.get_issue(
                issue_id_or_key,
                fields="summary",
                expand="changelog",
            )
            changelog = issue_data.get("changelog")
            if isinstance(changelog, dict):
                raw_histories = changelog.get("histories")
                if isinstance(raw_histories, list):
                    return [h for h in raw_histories if isinstance(h, dict)]
            return []

    def search_jql_page(
        self,
        jql: str,
        fields: list[str] | None = None,
        expand: str | None = None,
        start_at: int = 0,
        max_results: int = DEFAULT_PAGE_SIZE,
        next_page_token: str | None = None,
    ) -> tuple[list[dict[str, Any]], str | None, int | None]:
        """Execute a single page of JQL search across Jira Cloud (v3) or Data Center (v2).

        Returns:
            (issues, next_page_token_or_offset, total_count_if_known)
        """
        requested_fields = fields or ["*all"]

        if self.api_version == "3":
            # Try modern Jira Cloud /rest/api/3/search/jql first, with fallback to /rest/api/2/search
            params: dict[str, Any] = {
                "jql": jql,
                "maxResults": max_results,
                "fields": ",".join(requested_fields),
            }
            if expand:
                params["expand"] = expand
            if next_page_token:
                params["nextPageToken"] = next_page_token

            try:
                data = self._get_json("/rest/api/3/search/jql", params=params)
                issues = data.get("issues")
                if isinstance(issues, list):
                    # If /rest/api/3/search/jql returned full issues with fields, use them directly;
                    # if it returned id-only stubs, bulkfetch or fetch full issues.
                    hydrated_issues = self._ensure_hydrated_issues(
                        [i for i in issues if isinstance(i, dict)],
                        requested_fields=requested_fields,
                    )
                    token = data.get("nextPageToken")
                    is_last = data.get("isLast", token is None)
                    next_token = str(token) if (token and not is_last) else None
                    return hydrated_issues, next_token, data.get("total")
            except JiraServiceManagementClientError as exc:
                if exc.status_code not in (400, 404, 405, 410):
                    raise
                logger.debug(
                    f"/rest/api/3/search/jql unavailable ({exc.status_code}), falling back to /rest/api/2/search"
                )

        # Standard /rest/api/2/search (or /rest/api/{version}/search) offset pagination
        effective_start = int(next_page_token) if next_page_token and next_page_token.isdigit() else start_at
        search_params: dict[str, Any] = {
            "jql": jql,
            "startAt": effective_start,
            "maxResults": max_results,
            "fields": ",".join(requested_fields),
        }
        if expand:
            search_params["expand"] = expand

        data = self._get_json("/rest/api/2/search", params=search_params)
        raw_issues = data.get("issues")
        issues_list = [i for i in raw_issues if isinstance(i, dict)] if isinstance(raw_issues, list) else []
        total = data.get("total")
        new_offset = effective_start + len(issues_list)
        has_more = (
            len(issues_list) > 0
            and (
                (isinstance(total, int) and new_offset < total)
                or (not isinstance(total, int) and len(issues_list) >= max_results)
            )
        )
        next_cursor = str(new_offset) if has_more else None
        return issues_list, next_cursor, total if isinstance(total, int) else None

    def _ensure_hydrated_issues(
        self,
        issues: list[dict[str, Any]],
        requested_fields: list[str],
    ) -> list[dict[str, Any]]:
        """Ensure issues returned from /rest/api/3/search/jql contain `fields`."""
        if not issues:
            return []
        # Check if issues already include fields
        if all(isinstance(issue.get("fields"), dict) and issue.get("fields") for issue in issues):
            return issues

        issue_ids_or_keys = [
            str(issue.get("id") or issue.get("key"))
            for issue in issues
            if issue.get("id") or issue.get("key")
        ]
        if not issue_ids_or_keys:
            return issues

        try:
            body: dict[str, Any] = {"issueIdsOrKeys": issue_ids_or_keys}
            if requested_fields and requested_fields != ["*all"]:
                body["fields"] = requested_fields
            bulk_data = self._post_json("/rest/api/3/issue/bulkfetch", json_body=body)
            bulk_issues = bulk_data.get("issues")
            if isinstance(bulk_issues, list) and bulk_issues:
                return [i for i in bulk_issues if isinstance(i, dict)]
        except JiraServiceManagementClientError:
            pass

        hydrated: list[dict[str, Any]] = []
        for key in issue_ids_or_keys:
            try:
                hydrated.append(self.get_issue(key, fields=",".join(requested_fields)))
            except JiraServiceManagementClientError as exc:
                logger.warning(f"Failed to fetch issue {key}: {exc}")
        return hydrated
