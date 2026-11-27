from __future__ import annotations

import base64
from collections.abc import Generator
from datetime import datetime, timezone
from typing import Any, Optional
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from models import (
    JSMComment,
    JSMRequest,
    JSMRequestType,
    JSMServiceDesk,
)


class ConnectorValidationError(Exception):
    pass


class CredentialExpiredError(Exception):
    pass


class InsufficientPermissionsError(Exception):
    pass


def parse_jira_datetime(date_str: Optional[str]) -> Optional[datetime]:
    if not date_str:
        return None
    clean_str = date_str.replace("Z", "+00:00")
    if len(clean_str) >= 28 and (clean_str[-5] == "+" or clean_str[-5] == "-"):
        clean_str = clean_str[:-2] + ":" + clean_str[-2:]
    try:
        return datetime.fromisoformat(clean_str).astimezone(timezone.utc)
    except Exception:
        return None


class JiraServiceManagementClient:
    def __init__(
        self,
        base_url: str,
        user_email: Optional[str] = None,
        api_token: Optional[str] = None,
        pat_token: Optional[str] = None,
        timeout: int = 30,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()

        retries = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 502, 503, 504],
            raise_on_status=False,
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retries))
        self.session.mount("http://", HTTPAdapter(max_retries=retries))

        if user_email and api_token:
            auth_str = f"{user_email}:{api_token}"
            encoded = base64.b64encode(auth_str.encode("utf-8")).decode("utf-8")
            self.session.headers.update(
                {
                    "Authorization": f"Basic {encoded}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "X-ExperimentalApi": "opt-in",
                }
            )
        elif pat_token:
            self.session.headers.update(
                {
                    "Authorization": f"Bearer {pat_token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "X-ExperimentalApi": "opt-in",
                }
            )
        else:
            raise ConnectorValidationError(
                "Must provide either (user_email and api_token) or pat_token for Jira Service Management."
            )

    def _handle_response(self, response: requests.Response) -> dict[str, Any]:
        if response.status_code == 401:
            raise CredentialExpiredError(
                "Jira Service Management authentication failed (401 Unauthorized)."
            )
        if response.status_code == 403:
            raise InsufficientPermissionsError(
                "Insufficient permissions for Jira Service Management API (403 Forbidden)."
            )
        if response.status_code >= 400:
            raise ConnectorValidationError(
                f"JSM API error {response.status_code}: {response.text[:300]}"
            )
        try:
            return response.json()
        except Exception:
            return {}

    def test_connection(self) -> bool:
        url = f"{self.base_url}/rest/servicedeskapi/info"
        resp = self.session.get(url, timeout=self.timeout)
        if resp.status_code == 200:
            return True
        url_sd = f"{self.base_url}/rest/servicedeskapi/servicedesk"
        resp_sd = self.session.get(url_sd, timeout=self.timeout)
        self._handle_response(resp_sd)
        return True

    def get_service_desks(self) -> list[JSMServiceDesk]:
        service_desks: list[JSMServiceDesk] = []
        start = 0
        limit = 50

        while True:
            url = f"{self.base_url}/rest/servicedeskapi/servicedesk?start={start}&limit={limit}"
            resp = self.session.get(url, timeout=self.timeout)
            data = self._handle_response(resp)

            values = data.get("values", [])
            for item in values:
                service_desks.append(
                    JSMServiceDesk(
                        id=str(item.get("id")),
                        project_id=str(item.get("projectId")),
                        project_name=item.get("projectName", ""),
                        project_key=item.get("projectKey", ""),
                    )
                )

            if data.get("isLastPage", True) or not values:
                break
            start += len(values)

        return service_desks

    def get_service_desk_by_key(self, project_key: str) -> Optional[JSMServiceDesk]:
        all_desks = self.get_service_desks()
        target = project_key.upper().strip()
        for desk in all_desks:
            if desk.project_key.upper().strip() == target:
                return desk
        return None

    def get_requests_page(
        self,
        service_desk_id: Optional[str] = None,
        start: int = 0,
        limit: int = 50,
        request_status: str = "ALL_REQUESTS",
        request_ownership: str = "ALL_REQUESTS",
    ) -> tuple[list[dict[str, Any]], bool]:
        if service_desk_id:
            url = (
                f"{self.base_url}/rest/servicedeskapi/servicedesk/{service_desk_id}/request"
                f"?start={start}&limit={limit}&requestStatus={request_status}&requestOwnership={request_ownership}"
            )
        else:
            url = (
                f"{self.base_url}/rest/servicedeskapi/request"
                f"?start={start}&limit={limit}&requestStatus={request_status}&requestOwnership={request_ownership}"
            )

        resp = self.session.get(url, timeout=self.timeout)
        data = self._handle_response(resp)
        values = data.get("values", [])
        is_last = data.get("isLastPage", True) or len(values) < limit
        return values, is_last

    def get_request_comments(
        self, issue_id_or_key: str, include_internal: bool = True
    ) -> list[JSMComment]:
        url = f"{self.base_url}/rest/servicedeskapi/request/{issue_id_or_key}/comment"
        resp = self.session.get(url, timeout=self.timeout)
        if resp.status_code == 404:
            return []
        data = self._handle_response(resp)
        values = data.get("values", [])

        comments: list[JSMComment] = []
        for c in values:
            is_public = c.get("public", True)
            if not include_internal and not is_public:
                continue

            author = c.get("author", {})
            created_dt = parse_jira_datetime((c.get("created", {}) or {}).get("iso8601"))

            comments.append(
                JSMComment(
                    id=str(c.get("id")),
                    body=c.get("body", ""),
                    author_name=author.get("displayName") or author.get("name"),
                    author_email=author.get("emailAddress"),
                    created=created_dt,
                    is_public=is_public,
                )
            )
        return comments

    def parse_request_item(
        self, item: dict[str, Any], include_comments: bool = True
    ) -> JSMRequest:
        issue_id = str(item.get("issueId"))
        issue_key = str(item.get("issueKey"))
        service_desk_id = str(item.get("serviceDeskId", ""))

        field_values = item.get("requestFieldValues", [])
        summary = ""
        description = None

        for f in field_values:
            field_id = f.get("fieldId")
            val = f.get("value")
            if field_id == "summary" and isinstance(val, str):
                summary = val
            elif field_id == "description" and isinstance(val, str):
                description = val

        if not summary:
            summary = item.get("summary") or f"Request {issue_key}"

        current_status = (item.get("currentStatus", {}) or {}).get("status", "Unknown")

        reporter = item.get("reporter", {}) or {}
        reporter_name = reporter.get("displayName") or reporter.get("name")
        reporter_email = reporter.get("emailAddress")

        assignee = item.get("assignee", {}) or {}
        assignee_name = assignee.get("displayName") or assignee.get("name")
        assignee_email = assignee.get("emailAddress")

        req_type = item.get("requestType", {}) or {}
        req_type_id = str(req_type.get("id")) if req_type.get("id") else None
        req_type_name = req_type.get("name")

        created_dt = parse_jira_datetime((item.get("createdDate", {}) or {}).get("iso8601"))
        updated_dt = parse_jira_datetime((item.get("updatedDate", {}) or {}).get("iso8601")) or created_dt

        comments = []
        if include_comments and issue_key:
            try:
                comments = self.get_request_comments(issue_key, include_internal=True)
            except Exception:
                comments = []

        return JSMRequest(
            issue_id=issue_id,
            issue_key=issue_key,
            summary=summary,
            description=description,
            service_desk_id=service_desk_id,
            request_type_id=req_type_id,
            request_type_name=req_type_name,
            status=current_status,
            reporter_name=reporter_name,
            reporter_email=reporter_email,
            assignee_name=assignee_name,
            assignee_email=assignee_email,
            created_date=created_dt,
            updated_date=updated_dt,
            comments=comments,
            raw_fields=item,
        )

    def iterate_all_requests(
        self,
        service_desk_id: Optional[str] = None,
        batch_size: int = 50,
        include_comments: bool = True,
    ) -> Generator[JSMRequest, None, None]:
        start = 0
        while True:
            raw_items, is_last = self.get_requests_page(
                service_desk_id=service_desk_id,
                start=start,
                limit=batch_size,
            )
            for item in raw_items:
                yield self.parse_request_item(item, include_comments=include_comments)

            if is_last or not raw_items:
                break
            start += len(raw_items)
