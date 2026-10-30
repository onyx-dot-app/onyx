from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Any, ClassVar
from urllib.parse import urlparse

import requests

from onyx.configs.app_configs import INDEX_BATCH_SIZE, REQUEST_TIMEOUT_SECONDS
from onyx.configs.constants import DocumentSource
from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    InsufficientPermissionsError,
    RateLimitedValidationError,
    UnexpectedValidationError,
)
from onyx.connectors.interfaces import (
    GenerateDocumentsOutput,
    GenerateSlimDocumentOutput,
    LoadConnector,
    PollConnector,
    SecondsSinceUnixEpoch,
    SlimConnector,
)
from onyx.connectors.jira.source_operations import JiraApiError, JiraSourceOperations
from onyx.connectors.jira.utils import rich_text
from onyx.connectors.models import (
    BasicExpertInfo,
    ConnectorMissingCredentialError,
    Document,
    HierarchyNode,
    SlimDocument,
    TextSection,
)
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface

_JSM_ID_PREFIX = "JSM_REQUEST_"
_JSM_PAGE_LIMIT = 50


class JSMResourceNotFoundError(UnexpectedValidationError):
    """Raised when a specific Jira Service Management endpoint returns HTTP 404."""


def _parse_jsm_datetime(value: Any) -> datetime | None:
    """Parse Jira Service Management date objects or ISO-8601 strings into UTC datetime."""
    if not value:
        return None
    if isinstance(value, dict):
        epoch_millis = value.get("epochMillis")
        if isinstance(epoch_millis, (int, float)):
            return datetime.fromtimestamp(epoch_millis / 1000.0, tz=timezone.utc)
        iso_str = value.get("iso8601") or value.get("jira")
        if isinstance(iso_str, str) and iso_str:
            value = iso_str
        else:
            return None
    if isinstance(value, str):
        normalized = value.strip()
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"
        elif (
            len(normalized) >= 5
            and (normalized[-5] in ("+", "-"))
            and ":" not in normalized[-5:]
        ):
            normalized = normalized[:-2] + ":" + normalized[-2:]
        try:
            dt = datetime.fromisoformat(normalized)
            if not dt.tzinfo:
                return dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            return None
    return None


def _extract_expert(user_dict: dict[str, Any] | None) -> BasicExpertInfo | None:
    """Extract BasicExpertInfo from a JSM user dictionary."""
    if not isinstance(user_dict, dict):
        return None
    display_name = user_dict.get("displayName") or user_dict.get("name")
    email = user_dict.get("emailAddress")
    if not display_name and not email:
        return None
    return BasicExpertInfo(display_name=display_name, email=email)


def _render_request_field_values(
    field_values: list[dict[str, Any]] | None,
    default_summary: str = "",
) -> tuple[str, list[str]]:
    """Render JSM request field values into summary and textual lines.

    Extracts summary and formats labels/values for descriptions, custom fields,
    and rendered HTML payloads.
    """
    summary = default_summary
    field_lines: list[str] = []
    if not isinstance(field_values, list):
        return summary, field_lines

    for fv in field_values:
        if not isinstance(fv, dict):
            continue
        field_id = str(fv.get("fieldId", ""))
        label = str(fv.get("label") or field_id)
        raw_val = fv.get("value")
        rendered_val = fv.get("renderedValue")

        if isinstance(rendered_val, dict) and rendered_val.get("html"):
            val_str = str(rendered_val["html"])
        elif isinstance(raw_val, dict):
            if raw_val.get("type") == "doc":
                val_str = rich_text(raw_val)
            else:
                val_str = str(
                    raw_val.get("name")
                    or raw_val.get("value")
                    or raw_val.get("displayName")
                    or raw_val
                )
        elif isinstance(raw_val, list):
            val_str = ", ".join(
                str(v.get("name") or v.get("value") or v if isinstance(v, dict) else v)
                for v in raw_val
            )
        elif raw_val is not None:
            val_str = str(raw_val)
        else:
            val_str = ""

        if field_id == "summary" and val_str:
            summary = val_str
        if val_str:
            field_lines.append(f"{label}: {val_str}")

    return summary, field_lines


def _format_sla_metrics(slas: list[dict[str, Any]]) -> list[str]:
    """Format ongoing and completed cycles from JSM SLA records."""
    sla_lines: list[str] = []
    for sla in slas:
        sla_name = str(sla.get("name") or "SLA")
        ongoing = sla.get("ongoingCycle")
        completed = sla.get("completedCycles")
        if isinstance(ongoing, dict):
            breached = ongoing.get("breached", False)
            sla_lines.append(f"{sla_name}: ongoing (breached={breached})")
        elif isinstance(completed, list) and completed:
            last_cycle = completed[-1]
            if isinstance(last_cycle, dict):
                breached = last_cycle.get("breached", False)
                sla_lines.append(f"{sla_name}: completed (breached={breached})")
    return sla_lines


class JiraServiceManagementConnector(LoadConnector, PollConnector, SlimConnector):
    """Connector for Atlassian Jira Service Management (JSM) REST API (`/rest/servicedeskapi`).

    Enumerates credential-visible project issues through Jira search. JSM supplies
    public request comments; Jira fields supply issue updates and SLA cycles.
    Agent access is required. Source issue-security restrictions still apply.
    """

    document_source_type: ClassVar[DocumentSource] = (
        DocumentSource.JIRA_SERVICE_MANAGEMENT
    )

    def __init__(
        self,
        batch_size: int = INDEX_BATCH_SIZE,
        service_desk_ids: str | list[str] | None = None,
        project_key: str | None = None,
        include_internal_comments: bool = False,
        max_active_sla_requests: int = 1000,
    ) -> None:
        self.batch_size = batch_size
        if not isinstance(include_internal_comments, bool):
            raise ConnectorValidationError(
                "Internal-comment selection must be a boolean."
            )
        self.include_internal_comments = include_internal_comments
        if batch_size < 1 or not 1 <= max_active_sla_requests <= 10000:
            raise ConnectorValidationError(
                "Invalid JSM batch size or SLA refresh limit."
            )
        self.max_active_sla_requests = max_active_sla_requests
        self.project_key = (
            project_key.strip().upper()
            if isinstance(project_key, str) and project_key.strip()
            else None
        )

        if isinstance(service_desk_ids, str):
            parsed_ids = [
                part.strip() for part in service_desk_ids.split(",") if part.strip()
            ]
            self.service_desk_ids: list[str] | None = parsed_ids or None
        elif isinstance(service_desk_ids, list):
            self.service_desk_ids = [
                str(x).strip() for x in service_desk_ids if str(x).strip()
            ]
        else:
            self.service_desk_ids = None

        self.base_url: str | None = None
        self.user_email: str | None = None
        self.api_token: str | None = None
        self.bearer_token: str | None = None
        self._session = requests.Session()
        self._jira: JiraSourceOperations | None = None

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        base_url = (
            credentials.get("jsm_base_url") or credentials.get("jira_base_url") or ""
        )
        user_email = credentials.get("jsm_user_email") or credentials.get(
            "jira_user_email"
        )
        api_token = credentials.get("jsm_api_token") or credentials.get(
            "jira_api_token"
        )
        bearer_token = credentials.get("jsm_bearer_token") or credentials.get(
            "jira_pat"
        )

        normalized_url = str(base_url).strip().rstrip("/")
        if not normalized_url:
            raise ConnectorMissingCredentialError(
                "Jira Service Management base URL (`jsm_base_url` or `jira_base_url`) is required"
            )

        parsed_url = urlparse(normalized_url)
        is_local = parsed_url.hostname in ("localhost", "127.0.0.1")
        if (
            not parsed_url.hostname
            or parsed_url.username
            or parsed_url.password
            or parsed_url.query
            or parsed_url.fragment
            or parsed_url.scheme not in ({"https", "http"} if is_local else {"https"})
        ):
            raise ConnectorValidationError(
                "Jira Service Management requires an HTTPS site URL without embedded credentials."
            )

        def text(value: Any) -> str | None:
            if value is None or value == "":
                return None
            if not isinstance(value, str):
                raise ConnectorValidationError("JSM credentials must contain strings.")
            return value.strip() or None

        user_email, api_token, bearer_token = (
            text(user_email),
            text(api_token),
            text(bearer_token),
        )
        if bool(user_email) != bool(api_token):
            raise ConnectorValidationError("Supply both the JSM email and API token.")
        if not bearer_token and not (user_email and api_token):
            raise ConnectorMissingCredentialError(
                "Jira Service Management requires either (`jsm_user_email` + `jsm_api_token`) or `jsm_bearer_token`"
            )

        self.base_url = normalized_url
        self.user_email = user_email
        self.api_token = api_token
        self.bearer_token = bearer_token
        jira_credentials = {"jira_api_token": bearer_token or api_token}
        if not bearer_token and user_email:
            jira_credentials["jira_user_email"] = user_email
        self._jira = JiraSourceOperations(
            credentials_provider=OnyxStaticCredentialsProvider(
                None, DocumentSource.JIRA.value, jira_credentials
            ),
            connector_specific_config={"jira_base_url": normalized_url},
        )
        return None

    def _api_get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        jira_api: bool = False,
    ) -> dict[str, Any]:
        if not self.base_url or (
            not self.bearer_token and not (self.user_email and self.api_token)
        ):
            raise ConnectorMissingCredentialError("jira_service_management")

        api = (
            f"api/{'2' if self.bearer_token else '3'}" if jira_api else "servicedeskapi"
        )
        url = f"{self.base_url}/rest/{api}/{path.lstrip('/')}"
        headers: dict[str, str] = {
            "Accept": "application/json",
            "X-ExperimentalApi": "opt-in",
        }
        auth: tuple[str, str] | None = None
        if self.bearer_token:
            headers["Authorization"] = f"Bearer {self.bearer_token}"
        elif self.user_email and self.api_token:
            auth = (self.user_email, self.api_token)

        try:
            response = self._session.get(
                url,
                headers=headers,
                auth=auth,
                params=params,
                timeout=REQUEST_TIMEOUT_SECONDS,
                allow_redirects=False,
            )
            response.raise_for_status()
            if not 200 <= response.status_code < 300:
                raise UnexpectedValidationError("Unexpected Jira redirect response.")
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            if status == 401:
                raise CredentialExpiredError(
                    "Invalid or expired Jira Service Management credentials (HTTP 401)."
                ) from e
            if status == 403:
                raise InsufficientPermissionsError(
                    "Insufficient permissions to access Jira Service Management (HTTP 403)."
                ) from e
            if status == 404:
                raise JSMResourceNotFoundError(
                    f"Jira Service Management resource not found (HTTP 404): {url}"
                ) from e
            if status == 429:
                raise RateLimitedValidationError(
                    "Jira Service Management rate limit exceeded (HTTP 429)."
                ) from e
            raise UnexpectedValidationError(
                f"Unexpected Jira Service Management HTTP error (status={status})."
            ) from e
        except requests.exceptions.RequestException:
            raise UnexpectedValidationError(
                "Jira Service Management request failed."
            ) from None

        try:
            data = response.json()
            if not isinstance(data, (dict, list)):
                raise UnexpectedValidationError("Invalid Jira response structure.")
            return data if isinstance(data, dict) else {"values": data}
        except ValueError as e:
            raise UnexpectedValidationError(
                "Invalid JSON returned by Jira Service Management API"
            ) from e

    def _paginate(
        self, path: str, extra_params: dict[str, Any] | None = None
    ) -> Iterator[dict[str, Any]]:
        start_index = 0
        seen: set[str] = set()
        while True:
            params: dict[str, Any] = {"start": start_index, "limit": _JSM_PAGE_LIMIT}
            if extra_params:
                params.update(extra_params)

            payload = self._api_get(path, params=params)
            values = payload.get("values")
            if not isinstance(values, list) or any(
                not isinstance(v, dict) for v in values
            ):
                raise UnexpectedValidationError(
                    "Incomplete JSM page: missing or invalid values."
                )
            if not values and payload.get("isLastPage") is not True:
                raise UnexpectedValidationError(
                    "Empty JSM page without a completion marker."
                )

            for item in values:
                item_id = str(item.get("id", ""))
                if not item_id or item_id in seen:
                    raise UnexpectedValidationError(
                        "JSM page has missing or repeated item IDs."
                    )
                seen.add(item_id)
                yield item

            is_last_page = payload.get("isLastPage")
            if isinstance(is_last_page, bool):
                if is_last_page:
                    break
            else:
                raise UnexpectedValidationError(
                    "JSM page has no valid completion marker."
                )
            start_index += len(values)

    def _list_service_desks(self) -> list[dict[str, Any]]:
        desks = list(self._paginate("servicedesk"))
        filtered: list[dict[str, Any]] = []
        for desk in desks:
            desk_id = str(desk.get("id", "")).strip()
            proj_key = str(desk.get("projectKey", "")).strip().upper()
            if (
                self.service_desk_ids is not None
                and desk_id not in self.service_desk_ids
            ):
                continue
            if self.project_key is not None and proj_key != self.project_key:
                continue
            filtered.append(desk)
        return filtered

    def _validated_desks(self) -> list[dict[str, Any]]:
        if not self.project_key and not self.service_desk_ids:
            raise ConnectorValidationError(
                "A specific Jira Service Management project key or service desk ID must be configured."
            )

        desks = self._list_service_desks()
        if not desks:
            target = self.project_key or self.service_desk_ids
            raise UnexpectedValidationError(
                f"Jira Service Management: no matching service desks visible for scope '{target}'."
            )
        visible_ids = {str(d.get("id")) for d in desks}
        if self.service_desk_ids and not set(self.service_desk_ids) <= visible_ids:
            raise InsufficientPermissionsError(
                "Not all configured service desks are visible."
            )
        for desk in desks:
            if not re.fullmatch(r"[A-Z][A-Z0-9_]*", str(desk.get("projectKey", ""))):
                raise UnexpectedValidationError(
                    "Service desk has no valid Jira project key."
                )
            desk_id = str(desk.get("id", ""))
            if not desk_id.isdigit():
                raise UnexpectedValidationError("Service desk has no valid ID.")
            # Unlike the customer request endpoint, queues require a desk agent.
            probe = self._api_get(
                f"servicedesk/{desk_id}/queue", {"limit": 1, "includeCount": False}
            )
            if not isinstance(probe.get("values"), list):
                raise UnexpectedValidationError(
                    "Invalid agent permission probe response."
                )
        return desks

    def validate_connector_settings(self) -> None:
        self._validated_desks()

    def _fetch_request_comments(self, issue_key: str) -> list[dict[str, Any]]:
        comments = list(self._paginate(f"request/{issue_key}/comment"))
        return [
            c
            for c in comments
            if c.get("public") is True
            or (self.include_internal_comments and c.get("public") is False)
        ]

    def _request_updated_at(
        self, req: dict[str, Any], comments: list[dict[str, Any]]
    ) -> datetime | None:
        candidates: list[datetime] = []
        issue_updated = _parse_jsm_datetime(req.get("updatedDate"))
        if issue_updated:
            return issue_updated
        created_dt = _parse_jsm_datetime(req.get("createdDate"))
        if created_dt:
            candidates.append(created_dt)

        current_status = req.get("currentStatus")
        if isinstance(current_status, dict):
            status_dt = _parse_jsm_datetime(current_status.get("statusDate"))
            if status_dt:
                candidates.append(status_dt)

        for comment in comments:
            if comment.get("public") is not True and not (
                self.include_internal_comments and comment.get("public") is False
            ):
                continue
            c_dt = _parse_jsm_datetime(comment.get("created"))
            if c_dt:
                candidates.append(c_dt)

        return max(candidates) if candidates else None

    def _convert_request_to_document(
        self,
        req: dict[str, Any],
        desk: dict[str, Any],
        comments: list[dict[str, Any]],
        slas: list[dict[str, Any]],
    ) -> Document:
        issue_key = str(req.get("issueKey") or req.get("issueId") or "UNKNOWN")
        desk_id = str(desk.get("id", ""))
        project_key = str(desk.get("projectKey", ""))
        project_name = str(desk.get("projectName") or project_key or "Service Desk")

        raw_links = req.get("_links")
        links = raw_links if isinstance(raw_links, dict) else {}
        web_link = (
            links.get("web")
            or links.get("agent")
            or f"{self.base_url}/browse/{issue_key}"
        )

        field_values = req.get("requestFieldValues")
        summary, field_lines = _render_request_field_values(
            field_values if isinstance(field_values, list) else None,
            default_summary=issue_key,
        )

        raw_status = req.get("currentStatus")
        current_status = raw_status if isinstance(raw_status, dict) else {}
        status_name = str(current_status.get("status") or "Unknown")
        status_category = str(current_status.get("statusCategory") or "")

        sections: list[TextSection] = []
        body_text = "\n".join(
            [
                f"Service Desk: {project_name} ({project_key})",
                f"Request Key: {issue_key}",
                f"Status: {status_name}",
                *field_lines,
            ]
        )
        sections.append(TextSection(link=web_link, text=body_text))

        sla_lines = _format_sla_metrics(slas)
        if sla_lines:
            sections.append(
                TextSection(
                    link=web_link,
                    text="SLA Metrics:\n" + "\n".join(sla_lines),
                )
            )

        secondary_owners: list[BasicExpertInfo] = []
        for comment in comments:
            if comment.get("public") is not True and not (
                self.include_internal_comments and comment.get("public") is False
            ):
                continue
            body = str(comment.get("body") or "").strip()
            if not body:
                continue
            author = (
                comment.get("author")
                if isinstance(comment.get("author"), dict)
                else None
            )
            author_name = (
                str(author.get("displayName") or author.get("name") or "User")
                if author
                else "User"
            )
            visibility = "Public" if comment.get("public") is True else "Internal"
            sections.append(
                TextSection(
                    link=web_link,
                    text=f"[{visibility} Comment by {author_name}]: {body}",
                )
            )
            expert = _extract_expert(author)
            if expert and expert not in secondary_owners:
                secondary_owners.append(expert)

        reporter = _extract_expert(
            req.get("reporter") if isinstance(req.get("reporter"), dict) else None
        )
        primary_owners = [reporter] if reporter else None

        metadata: dict[str, str | list[str]] = {
            "issue_key": issue_key,
            "service_desk_id": desk_id,
            "status": status_name,
        }
        if project_key:
            metadata["project_key"] = project_key
        if status_category:
            metadata["status_category"] = status_category
        if req.get("requestTypeId") is not None:
            metadata["request_type_id"] = str(req["requestTypeId"])

        updated_at = self._request_updated_at(req, comments)
        created_at = _parse_jsm_datetime(req.get("createdDate"))

        return Document(
            id=f"{_JSM_ID_PREFIX}{issue_key}",
            sections=sections,
            source=DocumentSource.JIRA_SERVICE_MANAGEMENT,
            semantic_identifier=f"{issue_key}: {summary}",
            metadata=metadata,
            doc_updated_at=updated_at,
            doc_created_at=created_at,
            primary_owners=primary_owners,
            secondary_owners=secondary_owners or None,
        )

    def _iter_issues(
        self, jql: str, *, fields: str | None = None
    ) -> Iterator[dict[str, Any]]:
        """Use the existing Jira gateway for Cloud cursor/DC offset search.

        Cloud bulk fetch can omit inaccessible IDs. Fail rather than let an
        incomplete listing authorize pruning. Short DC pages are not EOF.
        """
        if self._jira is None:
            raise ConnectorMissingCredentialError("jira_service_management")
        token: str | None = None
        tokens: set[str] = set()
        seen: set[str] = set()
        offset = 0
        try:
            while True:
                if self.bearer_token:
                    issues = self._jira.search_issues(
                        jql=jql,
                        start_at=offset,
                        max_results=_JSM_PAGE_LIMIT,
                        fields=fields,
                        require_complete_page=True,
                    )
                    if not issues:
                        return
                    offset += len(issues)
                else:
                    page = self._jira.search_issue_ids(
                        jql=jql,
                        next_page_token=token,
                        max_results=_JSM_PAGE_LIMIT,
                        require_completion_marker=True,
                    )
                    issues = (
                        self._jira.bulk_fetch_issues(
                            issue_ids=page.issue_ids, fields=fields
                        )
                        if page.issue_ids
                        else []
                    )
                    if {str(issue.get("id")) for issue in issues} != set(
                        page.issue_ids
                    ) or len(issues) != len(page.issue_ids):
                        raise UnexpectedValidationError(
                            "Jira bulk fetch omitted or duplicated searched issues."
                        )
                    token = page.next_page_token
                    if token and token in tokens:
                        raise UnexpectedValidationError(
                            "Jira search repeated its cursor."
                        )
                    if token:
                        tokens.add(token)
                for issue in issues:
                    key = issue.get("key")
                    if (
                        not isinstance(key, str)
                        or key in seen
                        or not isinstance(issue.get("fields"), dict)
                    ):
                        raise UnexpectedValidationError(
                            "Jira returned an invalid or repeated issue."
                        )
                    seen.add(key)
                    yield issue
                if not self.bearer_token and token is None:
                    return
        except JiraApiError as exc:
            if exc.status_code == 400:
                raise ConnectorValidationError(
                    "Jira rejected the scoped issue/SLA query; check project fields and permissions."
                ) from None
            if exc.status_code == 401:
                raise CredentialExpiredError(
                    "Jira search credentials expired."
                ) from None
            if exc.status_code == 403:
                raise InsufficientPermissionsError(
                    "Jira project search was forbidden."
                ) from None
            if exc.status_code == 429:
                raise RateLimitedValidationError(
                    "Jira search rate limit exceeded."
                ) from None
            raise UnexpectedValidationError(
                "Jira project search failed; retry the indexing run."
            ) from None

    def _field_metadata(self) -> tuple[dict[str, str], set[str], set[str]]:
        fields = self._api_get("field", jira_api=True).get("values")
        if not isinstance(fields, list):
            raise UnexpectedValidationError("Jira did not return field metadata.")
        names: dict[str, str] = {}
        request_types: set[str] = set()
        sla_fields: set[str] = set()
        for field in fields:
            if not isinstance(field, dict) or not isinstance(field.get("id"), str):
                raise UnexpectedValidationError(
                    "Jira returned malformed field metadata."
                )
            key = field["id"]
            names[key] = str(field.get("name") or key)
            schema = field.get("schema") or {}
            if not isinstance(schema, dict):
                raise UnexpectedValidationError("Invalid Jira field schema.")
            if schema.get("custom") == "com.atlassian.servicedesk:vp-origin":
                request_types.add(key)
            if schema.get("custom") == "com.atlassian.servicedesk:sd-sla-field":
                if not re.fullmatch(r"customfield_\d+", key):
                    raise UnexpectedValidationError("Invalid Jira SLA field ID.")
                sla_fields.add(key)
        if not request_types:
            raise UnexpectedValidationError(
                "JSM request-type metadata is unavailable to this credential."
            )
        return names, request_types, sla_fields

    def _check_issue_scope(self, issue: dict[str, Any], desk: dict[str, Any]) -> None:
        key = issue["key"]
        project = str(desk["projectKey"])
        if not re.fullmatch(rf"{re.escape(project)}-\d+", key):
            raise UnexpectedValidationError(
                "Jira returned an issue outside the selected project."
            )
        fields = issue["fields"]
        if (
            not isinstance(fields.get("project"), dict)
            or fields["project"].get("key") != project
        ):
            raise UnexpectedValidationError(
                "Jira issue project metadata does not match the selected scope."
            )

    def _issue_content(
        self,
        issue: dict[str, Any],
        names: dict[str, str],
        request_types: set[str],
        sla_fields: set[str],
    ) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
        fields = issue["fields"]
        if _parse_jsm_datetime(fields.get("updated")) is None:
            raise UnexpectedValidationError("Jira issue has no valid update cursor.")
        request_fields = [
            {
                "fieldId": key,
                "label": names.get(key, key),
                "value": (
                    rich_text(value)
                    if key == "description"
                    or (isinstance(value, dict) and value.get("type") == "doc")
                    else value
                ),
            }
            for key, value in fields.items()
            if key in {"summary", "description"}
            or (
                key.startswith("customfield_") and key not in request_types | sla_fields
            )
        ]
        status = fields.get("status") or {}
        req = {
            "issueKey": issue["key"],
            "issueId": issue.get("id"),
            "createdDate": fields.get("created"),
            "updatedDate": fields["updated"],
            "reporter": fields.get("reporter"),
            "requestFieldValues": request_fields,
            "currentStatus": {
                "status": status.get("name"),
                "statusCategory": (status.get("statusCategory") or {}).get("name"),
            },
            "_links": {"web": f"{self.base_url}/browse/{issue['key']}"},
        }
        if not any(key in fields for key in request_types):
            raise UnexpectedValidationError(
                "Jira omitted the issue request-type field."
            )
        is_request = any(fields.get(key) is not None for key in request_types)
        for key in request_types:
            value = fields.get(key)
            if isinstance(value, dict) and isinstance(value.get("requestType"), dict):
                req["requestTypeId"] = value["requestType"].get("id")
        comments = self._fetch_request_comments(issue["key"]) if is_request else []
        if not is_request and self.include_internal_comments:
            comments = self._fetch_issue_comments(issue["key"])
        slas = [
            dict(fields[key], name=names[key])
            for key in sorted(sla_fields)
            if isinstance(fields.get(key), dict)
        ]
        return req, comments, slas

    def _fetch_issue_comments(self, key: str) -> list[dict[str, Any]]:
        """Non-customer Jira issue comments are internal; only fetch on explicit opt-in."""
        comments: list[dict[str, Any]] = []
        seen: set[str] = set()
        while True:
            page = self._api_get(
                f"issue/{key}/comment",
                {"startAt": len(comments), "maxResults": _JSM_PAGE_LIMIT},
                jira_api=True,
            )
            rows, total = page.get("comments"), page.get("total")
            if (
                not isinstance(rows, list)
                or not isinstance(total, int)
                or any(not isinstance(c, dict) for c in rows)
            ):
                raise UnexpectedValidationError("Invalid Jira comment page.")
            if not rows and len(comments) < total:
                raise UnexpectedValidationError(
                    "Jira comment listing ended prematurely."
                )
            for comment in rows:
                comment_id = str(comment.get("id", ""))
                if not comment_id or comment_id in seen:
                    raise UnexpectedValidationError(
                        "Jira comment page has missing or repeated IDs."
                    )
                seen.add(comment_id)
            comments.extend(
                dict(c, body=rich_text(c.get("body")), public=False) for c in rows
            )
            if len(comments) >= total:
                return comments

    def _process_requests(
        self, start: datetime | None = None, end: datetime | None = None
    ) -> GenerateDocumentsOutput:
        desks = self._validated_desks()
        names, request_types, sla_fields = self._field_metadata()
        active: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
        # A running/paused SLA can breach without Jira's updated value changing.
        # Fetch that set before yielding documents; never silently truncate it.
        if start and end and start.timestamp() > 0 and sla_fields:
            sla_clauses = " OR ".join(
                f"cf[{key.removeprefix('customfield_')}] = {function}()"
                for key in sorted(sla_fields)
                for function in ("running", "paused")
            )
            for desk in desks:
                jql = f'project = "{desk["projectKey"]}" AND updated <= {int(end.timestamp() * 1000)} AND ({sla_clauses}) ORDER BY key ASC'
                for issue in self._iter_issues(jql):
                    self._check_issue_scope(issue, desk)
                    updated = _parse_jsm_datetime(issue["fields"].get("updated"))
                    if updated is None:
                        raise UnexpectedValidationError(
                            "Jira issue has no valid update cursor."
                        )
                    if updated > end:
                        continue
                    active[issue["key"]] = (issue, desk)
                    if len(active) > self.max_active_sla_requests:
                        raise ConnectorValidationError(
                            "Active SLA refresh limit exceeded; narrow the project scope or increase max_active_sla_requests."
                        )
        doc_batch: list[Document | HierarchyNode] = []
        seen: set[str] = set()
        for desk in desks:
            jql = f'project = "{desk["projectKey"]}"'
            if start and end:
                jql += f" AND updated >= {int(start.timestamp() * 1000)} AND updated <= {int(end.timestamp() * 1000)}"
            for issue in self._iter_issues(jql + " ORDER BY key ASC"):
                self._check_issue_scope(issue, desk)
                if start and end:
                    updated = _parse_jsm_datetime(issue["fields"].get("updated"))
                    if updated is None:
                        raise UnexpectedValidationError(
                            "Jira issue has no valid update cursor."
                        )
                    if updated < start or updated > end:
                        continue
                key = issue["key"]
                if key in seen:
                    continue
                seen.add(key)
                # Active refresh uses the observed content once even if also updated.
                refreshed = key in active
                if refreshed:
                    active.pop(key)
                doc_batch.append(
                    self._issue_document(
                        issue, desk, names, request_types, sla_fields, end, refreshed
                    )
                )
                if len(doc_batch) >= self.batch_size:
                    yield doc_batch
                    doc_batch = []
        for issue, desk in active.values():
            doc_batch.append(
                self._issue_document(
                    issue, desk, names, request_types, sla_fields, end, True
                )
            )
            if len(doc_batch) >= self.batch_size:
                yield doc_batch
                doc_batch = []
        if doc_batch:
            yield doc_batch

    def _issue_document(
        self,
        issue: dict[str, Any],
        desk: dict[str, Any],
        names: dict[str, str],
        request_types: set[str],
        sla_fields: set[str],
        observed_at: datetime | None,
        refreshed: bool = False,
    ) -> Document:
        req, comments, slas = self._issue_content(
            issue, names, request_types, sla_fields
        )
        doc = self._convert_request_to_document(req, desk, comments, slas)
        if refreshed or any(isinstance(s.get("ongoingCycle"), dict) for s in slas):
            # A clock-only change must pass Onyx's timestamp dedup gate.
            doc.metadata["jira_updated_at"] = str(req["updatedDate"])
            doc.doc_updated_at = observed_at or datetime.now(timezone.utc)
        return doc

    def load_from_state(self) -> GenerateDocumentsOutput:
        return self._process_requests()

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        start_dt = datetime.fromtimestamp(start, tz=timezone.utc)
        end_dt = datetime.fromtimestamp(end, tz=timezone.utc)
        if end_dt < start_dt:
            raise ConnectorValidationError("JSM polling end precedes start.")
        yield from self._process_requests(start=start_dt, end=end_dt)

    def retrieve_all_slim_docs(
        self,
        start: SecondsSinceUnixEpoch | None = None,  # noqa: ARG002
        end: SecondsSinceUnixEpoch | None = None,  # noqa: ARG002
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        slim_batch: list[SlimDocument | HierarchyNode] = []

        for desk in self._validated_desks():
            if callback and callback.should_stop():
                raise RuntimeError(
                    "JSM slim enumeration was interrupted; pruning is unsafe."
                )
            jql = f'project = "{desk["projectKey"]}" ORDER BY key ASC'
            for issue in self._iter_issues(jql, fields="created,project"):
                if callback and callback.should_stop():
                    raise RuntimeError(
                        "JSM slim enumeration was interrupted; pruning is unsafe."
                    )
                self._check_issue_scope(issue, desk)
                issue_key = issue["key"]
                created_at = _parse_jsm_datetime(issue["fields"].get("created"))
                slim_batch.append(
                    SlimDocument(
                        id=f"{_JSM_ID_PREFIX}{issue_key}",
                        doc_created_at=created_at,
                    )
                )

                if len(slim_batch) >= self.batch_size:
                    yield slim_batch
                    slim_batch = []

        if slim_batch:
            yield slim_batch
