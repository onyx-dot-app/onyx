"""Jira Service Management Connector for Onyx.

Indexes customer requests, service desk tickets, and incidents from
Jira Service Management (JSM) projects via the Atlassian JSM REST APIs
(/rest/servicedeskapi/request, /rest/servicedeskapi/servicedesk) and
enhanced JQL queries for JSM project issue types.
"""

from collections.abc import Generator
from datetime import datetime, timezone
import json
import os
import re
import time
from typing import Any

import requests

from onyx.configs.app_configs import (
    INDEX_BATCH_SIZE,
    JIRA_CONNECTOR_LABELS_TO_SKIP,
    REQUEST_TIMEOUT_SECONDS,
)
from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.miscellaneous_utils import scoped_url
from onyx.connectors.cross_connector_utils.rate_limit_wrapper import rl_requests
from onyx.connectors.exceptions import (
    CredentialExpiredError,
    InsufficientPermissionsError,
)
from onyx.connectors.interfaces import (
    GenerateDocumentsOutput,
    GenerateSlimDocumentOutput,
    LoadConnector,
    PollConnector,
    SecondsSinceUnixEpoch,
    SlimConnector,
)
from onyx.connectors.jira.utils import (
    best_effort_basic_expert_info,
    build_jira_url,
    get_comment_strs,
    get_issue_field,
    get_named_field,
    rich_text,
)
from onyx.connectors.models import (
    BasicExpertInfo,
    ConnectorMissingCredentialError,
    Document,
    SlimDocument,
    TextSection,
)
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger

logger = setup_logger()

# JSM / Jira endpoints
_JSM_SERVICEDESK_ENDPOINT = "/rest/servicedeskapi/servicedesk"
_JSM_REQUEST_ENDPOINT = "/rest/servicedeskapi/request"
_JIRA_V3_SEARCH_JQL_ENDPOINT = "/rest/api/3/search/jql"
_JIRA_V3_SEARCH_ENDPOINT = "/rest/api/3/search"
_JIRA_V2_SEARCH_ENDPOINT = "/rest/api/2/search"

# Standard JSM custom field ID for Customer Request Type (Cloud & Data Center convention)
_REQUEST_TYPE_CUSTOM_FIELD = "customfield_10010"

_SEARCH_FIELDS = [
    "key",
    "summary",
    "description",
    "comment",
    "status",
    "priority",
    "issuetype",
    "reporter",
    "assignee",
    "created",
    "updated",
    "labels",
    "project",
    _REQUEST_TYPE_CUSTOM_FIELD,
]


def _format_jql_timestamp(epoch: SecondsSinceUnixEpoch) -> str:
    """Format Unix timestamp for JQL query string."""
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def _parse_timestamp(raw: str | None) -> datetime | None:
    """Parse ISO formatted timestamp into UTC datetime."""
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def _build_jsm_jql(
    project_key: str | None = None,
    custom_jql: str | None = None,
    start: SecondsSinceUnixEpoch | None = None,
    end: SecondsSinceUnixEpoch | None = None,
) -> str:
    """Constructs a scoped JQL query for Jira Service Management requests."""
    clauses: list[str] = []

    if custom_jql:
        clauses.append(f"({custom_jql})")
    elif project_key:
        clauses.append(f'project = "{project_key}"')

    if start is not None:
        clauses.append(f'updated >= "{_format_jql_timestamp(start)}"')
    if end is not None:
        clauses.append(f'updated <= "{_format_jql_timestamp(end)}"')

    if not clauses:
        # Jira Cloud search/jql can reject queries without a search restriction.
        clauses.append("project is not EMPTY")

    return " AND ".join(clauses) + " ORDER BY updated ASC"


def _extract_request_type(issue: dict[str, Any]) -> str | None:
    """Extract Customer Request Type from Jira issue fields."""
    val = get_issue_field(issue, _REQUEST_TYPE_CUSTOM_FIELD)
    if isinstance(val, dict):
        # Format: {"requestType": {"name": "..."}, ...}
        req_type = val.get("requestType")
        if isinstance(req_type, dict) and req_type.get("name"):
            return str(req_type.get("name"))
        if val.get("name"):
            return str(val.get("name"))
    elif isinstance(val, str) and val:
        return val

    # Check fallback fields
    issuetype = get_named_field(issue, "issuetype")
    return issuetype


def _issue_to_document(
    issue: dict[str, Any],
    jira_base_url: str,
    comment_email_blacklist: tuple[str, ...] = (),
    labels_to_skip: set[str] | None = None,
) -> Document | None:
    """Converts a Jira issue representation into an Onyx Document."""
    labels_to_skip = labels_to_skip or set()
    issue_key = issue.get("key")
    if not issue_key:
        return None

    fields = issue.get("fields") or {}
    raw_labels = fields.get("labels") or []
    issue_labels = [str(label) for label in raw_labels if isinstance(label, str)]

    if any(label in labels_to_skip for label in issue_labels):
        logger.info("Skipping issue %s due to skipped labels", issue_key)
        return None

    page_url = build_jira_url(jira_base_url, issue_key)
    summary = rich_text(fields.get("summary")) or ""
    description = rich_text(fields.get("description")) or ""
    status = get_named_field(issue, "status") or ""
    priority = get_named_field(issue, "priority") or ""
    issue_type = get_named_field(issue, "issuetype") or ""
    request_type = _extract_request_type(issue) or issue_type

    project = fields.get("project") or {}
    project_key = project.get("key") if isinstance(project, dict) else ""
    project_name = project.get("name") if isinstance(project, dict) else ""

    people: set[BasicExpertInfo] = set()
    reporter_obj = fields.get("reporter")
    reporter_name = ""
    reporter_email = ""
    if reporter_obj and (reporter_info := best_effort_basic_expert_info(reporter_obj)):
        people.add(reporter_info)
        reporter_name = reporter_info.get_semantic_name() or ""
        reporter_email = reporter_info.get_email() or ""

    assignee_obj = fields.get("assignee")
    assignee_name = ""
    assignee_email = ""
    if assignee_obj and (assignee_info := best_effort_basic_expert_info(assignee_obj)):
        people.add(assignee_info)
        assignee_name = assignee_info.get_semantic_name() or ""
        assignee_email = assignee_info.get_email() or ""

    created_dt = _parse_timestamp(fields.get("created"))
    updated_dt = _parse_timestamp(fields.get("updated"))

    comments = get_comment_strs(issue, comment_email_blacklist=comment_email_blacklist)

    # Build structured Markdown representation
    lines: list[str] = [f"# [{issue_key}] {summary}\n"]

    overview_items = [
        ("Status", status),
        ("Priority", priority),
        ("Request Type", request_type),
        ("Issue Type", issue_type),
        ("Project", f"{project_name} ({project_key})" if project_name and project_key else project_key),
        ("Reporter", f"{reporter_name} <{reporter_email}>" if reporter_email else reporter_name),
        ("Assignee", f"{assignee_name} <{assignee_email}>" if assignee_email else assignee_name),
        ("Created", fields.get("created")),
        ("Updated", fields.get("updated")),
    ]
    overview_lines = [f"- **{label}**: {val}" for label, val in overview_items if val]
    if overview_lines:
        lines.append("### Request Details\n" + "\n".join(overview_lines) + "\n")

    if description:
        lines.append("### Description\n" + description + "\n")

    if comments:
        lines.append("### Comments\n" + "\n\n".join(comments) + "\n")

    full_text = "\n".join(lines)

    metadata: dict[str, Any] = {
        "key": issue_key,
        "jira_issue_key": issue_key,
        "status": status,
        "priority": priority,
        "issue_type": issue_type,
        "request_type": request_type,
        "project": project_key,
        "project_name": project_name,
        "reporter": reporter_name,
        "reporter_email": reporter_email,
        "assignee": assignee_name,
        "assignee_email": assignee_email,
        "created": fields.get("created", ""),
        "updated": fields.get("updated", ""),
    }
    if issue_labels:
        metadata["labels"] = issue_labels

    return Document(
        id=page_url,
        sections=[TextSection(link=page_url, text=full_text)],
        source=DocumentSource.JIRA_SERVICE_MANAGEMENT,
        semantic_identifier=f"{issue_key}: {summary}" if summary else issue_key,
        title=f"{issue_key} {summary}".strip(),
        doc_updated_at=updated_dt,
        doc_created_at=created_dt,
        primary_owners=list(people) or None,
        metadata=metadata,
    )


def _request_to_document(
    req: dict[str, Any],
    jira_base_url: str,
    comments: list[dict[str, Any]] | None = None,
    comment_email_blacklist: tuple[str, ...] = (),
    labels_to_skip: set[str] | None = None,
) -> Document | None:
    """Converts a Jira Service Management /rest/servicedeskapi/request object into an Onyx Document."""
    issue_key = req.get("issueKey") or req.get("issueId")
    if not issue_key:
        return None

    page_url = build_jira_url(jira_base_url, issue_key)

    field_values = req.get("requestFieldValues") or []
    summary = ""
    description = ""
    priority = ""
    req_labels: list[str] = []
    updated_dt: datetime | None = None

    for fv in field_values:
        fid = fv.get("fieldId")
        val = fv.get("value")
        if fid == "summary":
            summary = rich_text(val) if val else ""
        elif fid == "description":
            description = rich_text(val) if val else ""
        elif fid == "priority":
            if isinstance(val, dict):
                priority = val.get("name", "")
            elif isinstance(val, str):
                priority = val
        elif fid == "labels":
            if isinstance(val, list):
                req_labels = [str(item) for item in val]
            elif isinstance(val, str):
                req_labels = [val]
        elif fid == "updated" and isinstance(val, str):
            updated_dt = _parse_timestamp(val)

    if labels_to_skip and any(label in labels_to_skip for label in req_labels):
        return None

    current_status = req.get("currentStatus") or {}
    status = current_status.get("status", "")

    reporter_obj = req.get("reporter") or {}
    reporter_name = reporter_obj.get("displayName") or reporter_obj.get("name") or ""
    reporter_email = reporter_obj.get("emailAddress", "")

    created_info = req.get("createdDate") or {}
    created_iso = created_info.get("iso8601", "") if isinstance(created_info, dict) else str(created_info)
    created_dt = _parse_timestamp(created_iso)

    if not updated_dt:
        status_date = current_status.get("statusDate")
        if isinstance(status_date, dict):
            updated_dt = _parse_timestamp(status_date.get("iso8601"))
        elif status_date:
            updated_dt = _parse_timestamp(str(status_date))
    if not updated_dt:
        updated_dt = created_dt

    service_desk_id = str(req.get("serviceDeskId", ""))
    request_type_id = str(req.get("requestTypeId", ""))

    rendered_comments: list[str] = []
    if comments:
        for c in comments:
            c_created = c.get("created")
            if isinstance(c_created, dict):
                c_dt = _parse_timestamp(c_created.get("iso8601"))
            elif isinstance(c_created, str):
                c_dt = _parse_timestamp(c_created)
            else:
                c_dt = None
            if c_dt and (not updated_dt or c_dt > updated_dt):
                updated_dt = c_dt

            author = c.get("author") or {}
            author_email = author.get("emailAddress", "")
            if author_email and author_email in comment_email_blacklist:
                continue
            author_name = author.get("displayName") or author.get("name") or "User"
            body = rich_text(c.get("body")) or ""
            rendered_comments.append(f"**{author_name}**: {body}")

    lines: list[str] = [f"# [{issue_key}] {summary}\n"]
    overview_lines = [
        f"- **Status**: {status}" if status else "",
        f"- **Priority**: {priority}" if priority else "",
        f"- **Service Desk ID**: {service_desk_id}" if service_desk_id else "",
        f"- **Request Type ID**: {request_type_id}" if request_type_id else "",
        f"- **Reporter**: {reporter_name} <{reporter_email}>" if reporter_email else f"- **Reporter**: {reporter_name}" if reporter_name else "",
        f"- **Created**: {created_iso}" if created_iso else "",
    ]
    lines.append("### Request Details\n" + "\n".join([ol for ol in overview_lines if ol]) + "\n")

    if description:
        lines.append("### Description\n" + description + "\n")

    if rendered_comments:
        lines.append("### Comments\n" + "\n\n".join(rendered_comments) + "\n")

    full_text = "\n".join(lines)

    metadata: dict[str, Any] = {
        "key": issue_key,
        "jira_issue_key": issue_key,
        "status": status,
        "priority": priority,
        "service_desk_id": service_desk_id,
        "request_type_id": request_type_id,
        "reporter": reporter_name,
        "reporter_email": reporter_email,
        "created": created_iso,
    }
    if req_labels:
        metadata["labels"] = req_labels

    return Document(
        id=page_url,
        sections=[TextSection(link=page_url, text=full_text)],
        source=DocumentSource.JIRA_SERVICE_MANAGEMENT,
        semantic_identifier=f"{issue_key}: {summary}" if summary else issue_key,
        title=f"{issue_key} {summary}".strip(),
        doc_updated_at=updated_dt or created_dt,
        doc_created_at=created_dt,
        metadata=metadata,
    )


class JiraServiceManagementApiClient:
    """HTTP client interacting with Atlassian Jira & Jira Service Management APIs."""

    def __init__(
        self,
        jira_base_url: str,
        jira_user_email: str | None,
        jira_api_token: str,
        scoped_token: bool = False,
    ) -> None:
        self.raw_base_url = jira_base_url.rstrip("/")
        if scoped_token:
            self.jira_base_url = scoped_url(self.raw_base_url, "jira").rstrip("/")
        else:
            self.jira_base_url = self.raw_base_url
        if jira_user_email:
            self.auth: tuple[str, str] | None = (jira_user_email, jira_api_token)
            self.headers = {"Accept": "application/json"}
        else:
            self.auth = None
            self.headers = {
                "Accept": "application/json",
                "Authorization": f"Bearer {jira_api_token}",
            }

    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = self.jira_base_url + path
        if method.upper() == "GET":
            response = rl_requests.get(
                url=url,
                params=params,
                auth=self.auth,
                headers=self.headers,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        elif method.upper() == "POST":
            response = rl_requests.post(
                url=url,
                json=json_data,
                params=params,
                auth=self.auth,
                headers=self.headers,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        else:
            response = requests.request(
                method=method,
                url=url,
                params=params,
                json=json_data,
                auth=self.auth,
                headers=self.headers,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )

        if response.status_code == 401:
            raise CredentialExpiredError(
                "Jira Service Management credentials are invalid or expired."
            )
        if response.status_code == 403:
            raise InsufficientPermissionsError(
                "Jira Service Management credentials lack required permissions."
            )

        response.raise_for_status()
        return response.json()

    def get_service_desks(self) -> list[dict[str, Any]]:
        """List service desks accessible by current credentials."""
        res = self._request("GET", _JSM_SERVICEDESK_ENDPOINT)
        return res.get("values", [])

    def get_customer_requests(
        self,
        service_desk_id: str | None = None,
        start: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Fetch customer requests from JSM Service Desk API."""
        if service_desk_id:
            path = f"{_JSM_SERVICEDESK_ENDPOINT}/{service_desk_id}/request"
        else:
            path = _JSM_REQUEST_ENDPOINT
        params: dict[str, Any] = {
            "start": start,
            "limit": limit,
            "requestOwnership": "ALL_REQUESTS",
        }
        return self._request("GET", path, params=params)

    def get_request_comments(self, issue_id_or_key: str) -> list[dict[str, Any]]:
        """Fetch all paginated comments for a specific customer request."""
        path = f"{_JSM_REQUEST_ENDPOINT}/{issue_id_or_key}/comment"
        all_comments: list[dict[str, Any]] = []
        start = 0
        limit = 50
        try:
            while True:
                res = self._request(
                    "GET", path, params={"start": start, "limit": limit}
                )
                page_values = res.get("values", [])
                if isinstance(page_values, list):
                    all_comments.extend(page_values)
                if res.get("isLastPage", True) or not page_values:
                    break
                start += len(page_values)
            return all_comments
        except Exception as e:
            logger.warning("Failed to fetch comments for request %s: %s", issue_id_or_key, e)
            raise

    def search_issues_jql(
        self,
        jql: str,
        next_page_token: str | None = None,
        start_at: int = 0,
        max_results: int = 50,
        fields: list[str] | None = None,
    ) -> dict[str, Any]:
        """Search issues using enhanced JQL search or standard search."""
        fields_str = ",".join(fields or _SEARCH_FIELDS)
        params: dict[str, Any] = {
            "jql": jql,
            "maxResults": max_results,
            "fields": fields_str,
        }
        if next_page_token:
            params["nextPageToken"] = next_page_token
        elif start_at > 0:
            params["startAt"] = start_at

        # Try enhanced JQL search first (Cloud v3), fallback to classic search
        for endpoint in (_JIRA_V3_SEARCH_JQL_ENDPOINT, _JIRA_V3_SEARCH_ENDPOINT, _JIRA_V2_SEARCH_ENDPOINT):
            try:
                return self._request("GET", endpoint, params=params)
            except requests.exceptions.HTTPError as e:
                if e.response is not None and e.response.status_code in (404, 410):
                    continue
                raise

        # If GET endpoints are not found, fallback to POST /rest/api/3/search with requested fields
        post_body: dict[str, Any] = {
            "jql": jql,
            "maxResults": max_results,
            "fields": fields or _SEARCH_FIELDS,
        }
        if next_page_token:
            post_body["nextPageToken"] = next_page_token
        elif start_at > 0:
            post_body["startAt"] = start_at
        return self._request("POST", _JIRA_V3_SEARCH_ENDPOINT, json_data=post_body)


class JiraServiceManagementConnector(
    LoadConnector,
    PollConnector,
    SlimConnector,
):
    """Indexes Jira Service Management customer requests and tickets."""

    def __init__(
        self,
        jira_base_url: str,
        project_key: str | None = None,
        service_desk_id: str | None = None,
        jql_query: str | None = None,
        comment_email_blacklist: list[str] | None = None,
        labels_to_skip: list[str] = JIRA_CONNECTOR_LABELS_TO_SKIP,
        batch_size: int = INDEX_BATCH_SIZE,
        scoped_token: bool = False,
    ) -> None:
        self.jira_base_url = (jira_base_url or "").rstrip("/")
        self.project_key = (project_key or "").strip() or None
        self.service_desk_id = (service_desk_id or "").strip() or None
        self.jql_query = (jql_query or "").strip() or None
        self.comment_email_blacklist = tuple(
            email.strip() for email in (comment_email_blacklist or []) if email.strip()
        )
        self.labels_to_skip = set(labels_to_skip)
        self.batch_size = batch_size
        self.scoped_token = scoped_token
        self.client: JiraServiceManagementApiClient | None = None

    def load_credentials(self, credentials: dict[str, Any]) -> None:
        """Load and validate Jira Service Management authentication credentials."""
        jira_base = credentials.get("jira_base_url") or self.jira_base_url
        if not jira_base:
            raise ConnectorMissingCredentialError("Jira Service Management Base URL")

        self.jira_base_url = jira_base.rstrip("/")
        jira_user_email = credentials.get("jira_user_email")
        jira_api_token = credentials.get("jira_api_token")

        if not jira_api_token:
            raise ConnectorMissingCredentialError(
                "Jira Service Management API Token / PAT"
            )

        self.client = JiraServiceManagementApiClient(
            jira_base_url=self.jira_base_url,
            jira_user_email=jira_user_email,
            jira_api_token=jira_api_token,
            scoped_token=self.scoped_token,
        )

    def _ensure_client(self) -> JiraServiceManagementApiClient:
        """Return the initialized API client or raise if credentials were not loaded."""
        if self.client is None:
            raise ConnectorMissingCredentialError("Jira Service Management")
        return self.client

    def _fetch_requests(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> GenerateDocumentsOutput:
        """Fetch and yield batches of JSM request or issue documents."""
        client = self._ensure_client()
        current_batch: list[Document] = []

        # If specific service desk ID is configured and no custom JQL, use JSM REST API directly
        if self.service_desk_id and not self.jql_query:
            start_dt = datetime.fromtimestamp(start, timezone.utc) if start is not None else None
            end_dt = datetime.fromtimestamp(end, timezone.utc) if end is not None else None
            start_idx = 0
            limit = 50
            while True:
                resp = client.get_customer_requests(
                    service_desk_id=self.service_desk_id,
                    start=start_idx,
                    limit=limit,
                )
                values = resp.get("values", [])
                for req in values:
                    issue_key = req.get("issueKey") or req.get("issueId")
                    comments = client.get_request_comments(issue_key) if issue_key else []
                    doc = _request_to_document(
                        req=req,
                        jira_base_url=self.jira_base_url,
                        comments=comments,
                        comment_email_blacklist=self.comment_email_blacklist,
                        labels_to_skip=self.labels_to_skip,
                    )
                    if doc is None:
                        continue
                    if start_dt is not None and doc.doc_updated_at and doc.doc_updated_at < start_dt:
                        continue
                    if end_dt is not None and doc.doc_updated_at and doc.doc_updated_at > end_dt:
                        continue

                    current_batch.append(doc)
                    if len(current_batch) >= self.batch_size:
                        yield current_batch
                        current_batch = []

                if resp.get("isLastPage", True) or not values:
                    break
                start_idx += len(values)

            if current_batch:
                yield current_batch
            return

        # Otherwise, query via JQL (scoped to JSM project or custom JQL query)
        jql = _build_jsm_jql(
            project_key=self.project_key,
            custom_jql=self.jql_query,
            start=start,
            end=end,
        )
        logger.info("Executing JSM JQL: %s", jql)

        next_page_token: str | None = None
        start_at = 0
        max_results = 50

        while True:
            resp = client.search_issues_jql(
                jql=jql,
                next_page_token=next_page_token,
                start_at=start_at,
                max_results=max_results,
            )
            issues = resp.get("issues", [])
            for issue in issues:
                doc = _issue_to_document(
                    issue=issue,
                    jira_base_url=self.jira_base_url,
                    comment_email_blacklist=self.comment_email_blacklist,
                    labels_to_skip=self.labels_to_skip,
                )
                if doc is not None:
                    current_batch.append(doc)
                    if len(current_batch) >= self.batch_size:
                        yield current_batch
                        current_batch = []

            next_page_token = resp.get("nextPageToken")
            total = resp.get("total", 0)
            start_at += len(issues)

            if next_page_token:
                continue
            if not issues or start_at >= total:
                break

        if current_batch:
            yield current_batch

    def load_from_state(self) -> GenerateDocumentsOutput:
        """Loads all documents from state."""
        return self._fetch_requests()

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        """Polls documents updated in time range [start, end]."""
        return self._fetch_requests(start=start, end=end)

    def retrieve_all_slim_docs(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        """Retrieves slim documents for all tickets in scope for pruning."""
        client = self._ensure_client()
        current_batch: list[SlimDocument] = []

        if self.service_desk_id and not self.jql_query:
            start_dt = datetime.fromtimestamp(start, timezone.utc) if start is not None else None
            end_dt = datetime.fromtimestamp(end, timezone.utc) if end is not None else None
            start_idx = 0
            limit = 50
            while True:
                if callback:
                    if callback.should_stop():
                        return
                    callback.progress("jsm_slim_docs", 0)
                resp = client.get_customer_requests(
                    service_desk_id=self.service_desk_id,
                    start=start_idx,
                    limit=limit,
                )
                values = resp.get("values", [])
                for req in values:
                    issue_key = req.get("issueKey") or req.get("issueId")
                    if not issue_key:
                        continue

                    field_values = req.get("requestFieldValues") or []
                    req_labels: list[str] = []
                    req_updated_dt: datetime | None = None
                    for fv in field_values:
                        fid = fv.get("fieldId")
                        val = fv.get("value")
                        if fid == "labels":
                            if isinstance(val, list):
                                req_labels = [str(item) for item in val]
                            elif isinstance(val, str):
                                req_labels = [val]
                        elif fid == "updated" and isinstance(val, str):
                            req_updated_dt = _parse_timestamp(val)

                    if self.labels_to_skip and any(label in self.labels_to_skip for label in req_labels):
                        continue

                    if not req_updated_dt:
                        status_date = (req.get("currentStatus") or {}).get("statusDate")
                        if isinstance(status_date, dict):
                            req_updated_dt = _parse_timestamp(status_date.get("iso8601"))
                        elif status_date:
                            req_updated_dt = _parse_timestamp(str(status_date))
                    if not req_updated_dt:
                        created_info = req.get("createdDate") or {}
                        created_iso = created_info.get("iso8601", "") if isinstance(created_info, dict) else str(created_info)
                        req_updated_dt = _parse_timestamp(created_iso)

                    if start_dt is not None or end_dt is not None:
                        try:
                            comments = client.get_request_comments(issue_key)
                            for c in comments:
                                c_created = c.get("created")
                                if isinstance(c_created, dict):
                                    c_dt = _parse_timestamp(c_created.get("iso8601"))
                                elif isinstance(c_created, str):
                                    c_dt = _parse_timestamp(c_created)
                                else:
                                    c_dt = None
                                if c_dt and (not req_updated_dt or c_dt > req_updated_dt):
                                    req_updated_dt = c_dt
                        except Exception as e:
                            logger.warning(
                                "Failed to fetch comments for slim doc timestamp check on %s: %s",
                                issue_key,
                                e,
                            )
                            raise

                    if start_dt is not None and req_updated_dt and req_updated_dt < start_dt:
                        continue
                    if end_dt is not None and req_updated_dt and req_updated_dt > end_dt:
                        continue

                    current_batch.append(
                        SlimDocument(id=build_jira_url(self.jira_base_url, issue_key))
                    )
                    if len(current_batch) >= self.batch_size:
                        yield current_batch
                        current_batch = []

                if resp.get("isLastPage", True) or not values:
                    break
                start_idx += len(values)

            if current_batch:
                yield current_batch
            return

        jql = _build_jsm_jql(
            project_key=self.project_key,
            custom_jql=self.jql_query,
            start=start,
            end=end,
        )

        next_page_token: str | None = None
        start_at = 0
        max_results = 100

        while True:
            if callback:
                if callback.should_stop():
                    return
                callback.progress("jsm_slim_docs", 0)
            resp = client.search_issues_jql(
                jql=jql,
                next_page_token=next_page_token,
                start_at=start_at,
                max_results=max_results,
                fields=["key", "labels"],
            )
            issues = resp.get("issues", [])
            for issue in issues:
                issue_key = issue.get("key")
                if not issue_key:
                    continue
                fields = issue.get("fields") or {}
                raw_labels = fields.get("labels") or []
                if any(label in self.labels_to_skip for label in raw_labels):
                    continue

                current_batch.append(
                    SlimDocument(id=build_jira_url(self.jira_base_url, issue_key))
                )
                if len(current_batch) >= self.batch_size:
                    yield current_batch
                    current_batch = []

            next_page_token = resp.get("nextPageToken")
            total = resp.get("total", 0)
            start_at += len(issues)

            if next_page_token:
                continue
            if not issues or start_at >= total:
                break

        if current_batch:
            yield current_batch
