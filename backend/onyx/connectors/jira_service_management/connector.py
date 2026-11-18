from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Any

import requests

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.rate_limit_wrapper import rl_requests
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    InsufficientPermissionsError,
)
from onyx.connectors.interfaces import (
    GenerateDocumentsOutput,
    LoadConnector,
    PollConnector,
    SecondsSinceUnixEpoch,
)
from onyx.connectors.models import (
    BasicExpertInfo,
    ConnectorMissingCredentialError,
    Document,
    HierarchyNode,
    TextSection,
)
from onyx.utils.logger import setup_logger
from onyx.utils.retry_wrapper import retry_builder

logger = setup_logger()

_JSM_ID_PREFIX = "JSM_"
_JSM_PAGE_LIMIT = 50
_DEFAULT_TIMEOUT_SECONDS = 30


@retry_builder(tries=3, delay=1, backoff=2)
def _rate_limited_jsm_get(
    url: str,
    headers: dict[str, str],
    auth: tuple[str, str] | None,
    params: dict[str, Any] | None = None,
) -> requests.Response:
    return rl_requests.get(
        url,
        headers=headers,
        auth=auth,
        params=params,
        timeout=_DEFAULT_TIMEOUT_SECONDS,
    )


def _normalize_base_url(raw_url: str) -> str:
    url = raw_url.strip().rstrip("/")
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"
    return url


def _parse_jsm_datetime(date_obj: Any) -> datetime | None:
    """Parse a JSM date payload ({iso8601, epochMillis}) or ISO-8601 string to UTC."""
    if not date_obj:
        return None

    if isinstance(date_obj, dict):
        iso_val = date_obj.get("iso8601")
        if isinstance(iso_val, str) and iso_val:
            parsed = datetime.fromisoformat(iso_val)
            return (
                parsed.replace(tzinfo=timezone.utc)
                if parsed.tzinfo is None
                else parsed.astimezone(timezone.utc)
            )
        epoch_ms = date_obj.get("epochMillis")
        if isinstance(epoch_ms, (int, float)):
            return datetime.fromtimestamp(epoch_ms / 1000.0, tz=timezone.utc)
        return None

    if isinstance(date_obj, str):
        parsed = datetime.fromisoformat(date_obj)
        return (
            parsed.replace(tzinfo=timezone.utc)
            if parsed.tzinfo is None
            else parsed.astimezone(timezone.utc)
        )

    return None


def _extract_field_value_text(value: Any) -> str:
    """Convert a JSM requestFieldValues entry value into readable plain text."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, dict):
        for key in ("name", "value", "displayName", "label", "key"):
            if key in value and value[key] is not None:
                return str(value[key]).strip()
        return ", ".join(
            f"{k}: {_extract_field_value_text(v)}"
            for k, v in value.items()
            if v is not None
        )
    if isinstance(value, list):
        parts = [_extract_field_value_text(item) for item in value]
        return ", ".join(p for p in parts if p)
    return str(value)


def _build_expert_info(user_obj: dict[str, Any] | None) -> BasicExpertInfo | None:
    if not isinstance(user_obj, dict):
        return None
    display_name = user_obj.get("displayName") or user_obj.get("name")
    email = user_obj.get("emailAddress")
    if not display_name and not email:
        return None
    return BasicExpertInfo(display_name=display_name, email=email)


def _format_comments_text(comments: list[dict[str, Any]]) -> str:
    if not comments:
        return ""
    lines: list[str] = ["Comments:"]
    for comment in comments:
        author = comment.get("author") or {}
        author_name = (
            author.get("displayName")
            or author.get("emailAddress")
            or "Unknown"
        )
        visibility = "Public" if comment.get("public", True) else "Internal"
        created_dt = _parse_jsm_datetime(comment.get("created"))
        timestamp_str = created_dt.isoformat() if created_dt else "Unknown time"
        body = (comment.get("body") or "").strip()
        if body:
            lines.append(f"[{timestamp_str}] {author_name} ({visibility}): {body}")
    return "\n".join(lines) if len(lines) > 1 else ""


def _create_document_from_request(
    request_data: dict[str, Any],
    comments: list[dict[str, Any]],
    base_url: str,
    project_key: str | None = None,
) -> Document:
    issue_key = str(request_data.get("issueKey") or request_data.get("issueId") or "")
    issue_id = str(request_data.get("issueId") or issue_key)
    service_desk_id = str(request_data.get("serviceDeskId") or "")

    links = request_data.get("_links") or {}
    ticket_url = links.get("web") or f"{base_url}/browse/{issue_key}"

    field_values = request_data.get("requestFieldValues") or []
    summary = ""
    description = ""
    extra_fields: list[str] = []
    priority_value: str | None = None

    for field in field_values:
        field_id = str(field.get("fieldId") or "").lower()
        label = str(field.get("label") or field.get("fieldId") or "").strip()
        text_val = _extract_field_value_text(field.get("value"))
        if not text_val:
            continue

        if field_id == "summary" and not summary:
            summary = text_val
        elif field_id == "description" and not description:
            description = text_val
        elif field_id == "priority":
            priority_value = text_val
            extra_fields.append(f"{label}: {text_val}")
        else:
            extra_fields.append(f"{label}: {text_val}")

    if not summary:
        summary = str(request_data.get("summary") or issue_key or "Service Desk Ticket")

    current_status = request_data.get("currentStatus") or {}
    status_name = current_status.get("status")
    status_category = current_status.get("statusCategory")
    request_type = (request_data.get("requestType") or {}).get("name")

    reporter_info = _build_expert_info(request_data.get("reporter"))
    assignee_info = _build_expert_info(request_data.get("assignee"))

    created_at = _parse_jsm_datetime(request_data.get("createdDate"))
    updated_candidates = [
        dt
        for dt in (
            created_at,
            _parse_jsm_datetime(current_status.get("statusDate")),
            _parse_jsm_datetime(request_data.get("updatedDate")),
            _parse_jsm_datetime(request_data.get("updated")),
            *(_parse_jsm_datetime(c.get("created")) for c in comments),
        )
        if dt is not None
    ]
    updated_at = max(updated_candidates) if updated_candidates else None

    body_parts: list[str] = [f"Ticket: {issue_key}" if issue_key else "Ticket"]
    if summary:
        body_parts.append(f"Summary: {summary}")
    if status_name:
        body_parts.append(f"Status: {status_name}")
    if request_type:
        body_parts.append(f"Request Type: {request_type}")
    if description:
        body_parts.append(f"Description:\n{description}")
    if extra_fields:
        body_parts.append("Fields:\n" + "\n".join(extra_fields))

    comments_text = _format_comments_text(comments)
    if comments_text:
        body_parts.append(comments_text)

    metadata: dict[str, str | list[str]] = {}
    if issue_key:
        metadata["issue_key"] = issue_key
    if issue_id:
        metadata["issue_id"] = issue_id
    if service_desk_id:
        metadata["service_desk_id"] = service_desk_id
    if project_key:
        metadata["project_key"] = project_key
    if status_name:
        metadata["status"] = str(status_name)
    if status_category:
        metadata["status_category"] = str(status_category)
    if request_type:
        metadata["request_type"] = str(request_type)
    if priority_value:
        metadata["priority"] = priority_value
    if reporter_info:
        metadata["reporter"] = reporter_info.get_semantic_name()
    metadata["comment_count"] = str(len(comments))

    semantic_id = f"{issue_key}: {summary}" if issue_key else summary

    return Document(
        id=f"{_JSM_ID_PREFIX}{ticket_url}",
        sections=[TextSection(link=ticket_url, text="\n\n".join(body_parts))],
        source=DocumentSource.JIRA_SERVICE_MANAGEMENT,
        semantic_identifier=semantic_id,
        title=f"[{issue_key}] {summary}" if issue_key else summary,
        metadata=metadata,
        primary_owners=[reporter_info] if reporter_info else None,
        secondary_owners=[assignee_info] if assignee_info else None,
        doc_created_at=created_at,
        doc_updated_at=updated_at,
    )


class JiraServiceManagementConnector(LoadConnector, PollConnector):
    """Connector for pulling customer tickets from Jira Service Management."""

    def __init__(
        self,
        base_url: str | None = None,
        project_key: str | None = None,
        service_desk_id: str | None = None,
        include_internal_comments: bool = False,
        batch_size: int = INDEX_BATCH_SIZE,
    ) -> None:
        self.base_url: str | None = (
            _normalize_base_url(base_url) if base_url else None
        )
        self.project_key = project_key.strip() if project_key else None
        self.service_desk_id = service_desk_id.strip() if service_desk_id else None
        self.include_internal_comments = include_internal_comments
        self.batch_size = batch_size

        self.api_token: str | None = None
        self.user_email: str | None = None

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        api_token = (
            credentials.get("jsm_api_token")
            or credentials.get("jira_api_token")
            or credentials.get("api_token")
        )
        user_email = (
            credentials.get("jsm_user_email")
            or credentials.get("jira_user_email")
            or credentials.get("user_email")
        )
        cred_base_url = (
            credentials.get("jsm_base_url")
            or credentials.get("jira_base_url")
            or credentials.get("base_url")
        )

        if not isinstance(api_token, str) or not api_token.strip():
            raise ConnectorMissingCredentialError(
                "Jira Service Management API token is required"
            )

        if not self.base_url:
            if not isinstance(cred_base_url, str) or not cred_base_url.strip():
                raise ConnectorMissingCredentialError(
                    "Jira Service Management base_url is required"
                )
            self.base_url = _normalize_base_url(cred_base_url)

        self.api_token = api_token.strip()
        self.user_email = (
            user_email.strip()
            if isinstance(user_email, str) and user_email.strip()
            else None
        )
        return None

    def _request_auth_and_headers(self) -> tuple[tuple[str, str] | None, dict[str, str]]:
        if not self.api_token or not self.base_url:
            raise ConnectorMissingCredentialError("jira_service_management")

        headers: dict[str, str] = {"Accept": "application/json"}
        if self.user_email:
            # Atlassian Cloud uses Basic auth with email + API token.
            return (self.user_email, self.api_token), headers

        # Data Center / Server personal access tokens use Bearer auth.
        headers["Authorization"] = f"Bearer {self.api_token}"
        return None, headers

    def _get_json(
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        auth, headers = self._request_auth_and_headers()
        url = f"{self.base_url}{path}"
        response = _rate_limited_jsm_get(url, headers=headers, auth=auth, params=params)

        if response.status_code == 401:
            raise CredentialExpiredError(
                "Jira Service Management credentials are invalid or expired"
            )
        if response.status_code == 403:
            raise InsufficientPermissionsError(
                "Insufficient permissions to access Jira Service Management"
            )

        response.raise_for_status()
        return response.json()

    def _paginate(
        self, path: str, params: dict[str, Any] | None = None
    ) -> Iterator[dict[str, Any]]:
        start = 0
        base_params = dict(params or {})

        while True:
            page_params = {
                **base_params,
                "start": start,
                "limit": _JSM_PAGE_LIMIT,
            }
            payload = self._get_json(path, params=page_params)
            values = payload.get("values") or []
            for item in values:
                yield item

            is_last = payload.get("isLastPage")
            if is_last is True or not values:
                break
            if is_last is None and len(values) < _JSM_PAGE_LIMIT:
                break

            start += len(values)

    def _resolve_service_desks(self) -> list[tuple[str, str | None]]:
        """Return list of (service_desk_id, project_key) pairs in scope."""
        if self.service_desk_id:
            return [(self.service_desk_id, self.project_key)]

        desks = list(self._paginate("/rest/servicedeskapi/servicedesk"))
        if self.project_key:
            target = self.project_key.lower()
            matched = [
                (str(desk["id"]), desk.get("projectKey"))
                for desk in desks
                if str(desk.get("projectKey") or "").lower() == target
            ]
            if not matched:
                raise ConnectorValidationError(
                    f"Jira Service Management project '{self.project_key}' not found"
                )
            return matched

        return [
            (str(desk["id"]), desk.get("projectKey"))
            for desk in desks
            if desk.get("id") is not None
        ]

    def validate_connector_settings(self) -> None:
        self._resolve_service_desks()

    def _fetch_comments(self, issue_key_or_id: str) -> list[dict[str, Any]]:
        comments: list[dict[str, Any]] = []
        for comment in self._paginate(
            f"/rest/servicedeskapi/request/{issue_key_or_id}/comment"
        ):
            is_public = comment.get("public", True)
            if not is_public and not self.include_internal_comments:
                continue
            comments.append(comment)
        return comments

    def _process_tickets(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> GenerateDocumentsOutput:
        if not self.base_url:
            raise ConnectorMissingCredentialError("jira_service_management")

        doc_batch: list[Document | HierarchyNode] = []

        for service_desk_id, resolved_project_key in self._resolve_service_desks():
            request_params: dict[str, Any] = {
                "serviceDeskId": service_desk_id,
                "requestOwnership": "ALL_REQUESTS",
                "requestStatus": "ALL_REQUESTS",
                "expand": "participant,status,requestType",
            }
            for ticket in self._paginate(
                "/rest/servicedeskapi/request", params=request_params
            ):
                issue_ref = str(
                    ticket.get("issueKey") or ticket.get("issueId") or ""
                )
                if not issue_ref:
                    continue

                comments = self._fetch_comments(issue_ref)
                document = _create_document_from_request(
                    request_data=ticket,
                    comments=comments,
                    base_url=self.base_url,
                    project_key=resolved_project_key,
                )

                effective_ts = document.doc_updated_at or document.doc_created_at
                if start is not None and effective_ts is not None and effective_ts < start:
                    continue
                if end is not None and effective_ts is not None and effective_ts > end:
                    continue

                doc_batch.append(document)
                if len(doc_batch) >= self.batch_size:
                    yield doc_batch
                    doc_batch = []

        if doc_batch:
            yield doc_batch

    def load_from_state(self) -> GenerateDocumentsOutput:
        yield from self._process_tickets()

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        start_dt = datetime.fromtimestamp(start, tz=timezone.utc)
        end_dt = datetime.fromtimestamp(end, tz=timezone.utc)
        yield from self._process_tickets(start=start_dt, end=end_dt)
