"""Jira Service Management (JSM) connector implementation."""

import copy
import json
import math
from datetime import datetime
from typing import Any
from urllib.parse import quote, urlparse

import requests
from pydantic import Field

from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialInvalidError,
    InsufficientPermissionsError,
)
from onyx.connectors.interfaces import (
    CheckpointedConnector,
    CheckpointOutput,
    ConnectorCheckpoint,
    SecondsSinceUnixEpoch,
)
from onyx.connectors.models import (
    BasicExpertInfo,
    ConnectorFailure,
    Document,
    DocumentFailure,
    EntityFailure,
    TextSection,
)

_BASE_SEARCH_FIELDS = (
    "summary,description,status,priority,comment,reporter,updated"
)
_REQUEST_TYPE_SCHEMA_CUSTOM = "com.atlassian.servicedesk:vp-origin"
_REQUEST_TYPE_SCHEMA_TYPE = "sd-customerrequesttype"
_REQUEST_TYPE_FIELD_NAMES = frozenset({"request type", "customer request type"})
_COMMENT_PAGE_SIZE = 100
_MAX_BOUNDARY_SEEN_KEYS = 200


def _escape_jql_string(value: str) -> str:
    """Escape backslashes and double quotes for a JQL string literal."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _normalize_base_url(raw_url: str) -> str:
    """Validate and normalize the configured JSM HTTPS base URL."""
    candidate = raw_url.strip().rstrip("/")
    if not candidate:
        raise ConnectorValidationError("Jira Service Management base_url is required.")
    parsed = urlparse(candidate)
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ConnectorValidationError(
            "Jira Service Management base_url must be a valid HTTPS base URL."
        )
    return f"https://{parsed.netloc}{parsed.path.rstrip('/')}"


def _comment_has_visibility_signal(comment: dict[str, Any]) -> bool:
    """Return True when a comment payload already carries JSM visibility metadata."""
    return (
        isinstance(comment.get("jsdPublic"), bool)
        or isinstance(comment.get("public"), bool)
        or isinstance(comment.get("properties"), list)
    )


def _is_public_comment(comment: dict[str, Any]) -> bool:
    """Return True only when a JSM comment is customer-visible and unrestricted."""
    if comment.get("jsdPublic") is False or comment.get("public") is False:
        return False
    if comment.get("visibility"):
        return False

    properties = comment.get("properties")
    if isinstance(properties, list):
        for prop in properties:
            if not isinstance(prop, dict):
                continue
            prop_key = str(prop.get("key") or "")
            if prop_key not in {"sd.public.comment", "sd.allow.public.comment"}:
                continue
            prop_val = prop.get("value")
            if isinstance(prop_val, str):
                try:
                    prop_val = json.loads(prop_val)
                except ValueError:
                    prop_val = None
            if isinstance(prop_val, dict) and (
                prop_val.get("internal") is True
                or prop_val.get("public") is False
                or prop_val.get("allow") is False
            ):
                return False
    return True


def _extract_request_type_name(field_value: Any) -> str:
    """Extract a human-readable request type name from a JSM custom field value."""
    if not isinstance(field_value, dict):
        return ""
    nested = field_value.get("requestType")
    if isinstance(nested, dict):
        nested_name = str(nested.get("name") or "").strip()
        if nested_name:
            return nested_name
    direct_name = str(field_value.get("name") or "").strip()
    return direct_name


class JSMConnectorCheckpoint(ConnectorCheckpoint):
    """Checkpoint state for Jira Service Management token-based pagination."""

    next_page_token: str | None = None
    last_updated_value: str | None = None
    seen_issue_keys: list[str] = Field(default_factory=list)


class JiraServiceManagementConnector(CheckpointedConnector[JSMConnectorCheckpoint]):
    """Connector for Atlassian Jira Service Management REST APIs."""

    def __init__(
        self,
        base_url: str,
        project_key: str = "",
        service_desk_id: str = "",
        batch_size: int = 50,
        include_comments: bool = True,
    ) -> None:
        """Initialize the Jira Service Management connector configuration."""
        self.base_url = base_url.strip().rstrip("/")
        self.project_key = project_key.strip()
        self.service_desk_id = service_desk_id.strip()
        self.batch_size = batch_size
        self.include_comments = include_comments
        self._email: str = ""
        self._api_token: str = ""
        self._resolved_project_key: str = ""
        self._request_type_field_id: str | None = None
        self._request_type_field_resolved: bool = False

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        """Load Atlassian user email and API token from the credential dictionary."""
        self._email = str(
            credentials.get("jira_user_email")
            or credentials.get("jsm_user_email")
            or ""
        ).strip()
        self._api_token = str(
            credentials.get("jira_api_token") or credentials.get("jsm_api_token") or ""
        ).strip()
        return None

    def build_dummy_checkpoint(self) -> JSMConnectorCheckpoint:
        """Create an initial checkpoint for a new JSM indexing window."""
        return JSMConnectorCheckpoint(has_more=True)

    def validate_checkpoint_json(self, checkpoint_json: str) -> JSMConnectorCheckpoint:
        """Validate and deserialize persisted checkpoint JSON."""
        return JSMConnectorCheckpoint.model_validate_json(checkpoint_json)

    def _request_json(
        self,
        api_path: str,
        params: dict[str, Any] | None = None,
        timeout: int = 30,
    ) -> Any:
        """Execute an authenticated GET request and return decoded JSON."""
        normalized_base = _normalize_base_url(self.base_url)
        clean_path = api_path if api_path.startswith("/") else f"/{api_path}"
        resp = requests.get(
            f"{normalized_base}{clean_path}",
            params=params,
            auth=(self._email, self._api_token),
            headers={"Accept": "application/json"},
            timeout=timeout,
        )
        if resp.status_code == 401:
            raise CredentialInvalidError(
                "Invalid Jira Service Management credentials (HTTP 401)."
            )
        if resp.status_code == 403:
            raise InsufficientPermissionsError(
                "Insufficient Jira Service Management permissions (HTTP 403)."
            )
        resp.raise_for_status()
        return resp.json()

    def _get(
        self,
        api_path: str,
        params: dict[str, Any] | None = None,
        timeout: int = 30,
    ) -> dict[str, Any]:
        """Execute an authenticated GET request returning a JSON object."""
        payload = self._request_json(api_path, params=params, timeout=timeout)
        if not isinstance(payload, dict):
            raise ValueError("Expected JSON object from Jira Service Management API.")
        return payload

    def _resolve_request_type_field_id(self, timeout: int = 15) -> str | None:
        """Discover and cache the Jira site's Customer Request Type field ID."""
        if self._request_type_field_resolved:
            return self._request_type_field_id

        try:
            payload = self._request_json("/rest/api/3/field", timeout=timeout)
        except InsufficientPermissionsError:
            self._request_type_field_resolved = True
            self._request_type_field_id = None
            return None
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                self._request_type_field_resolved = True
                self._request_type_field_id = None
                return None
            raise

        matched_id: str | None = None
        if isinstance(payload, list):
            for entry in payload:
                if not isinstance(entry, dict):
                    continue
                schema = entry.get("schema")
                if isinstance(schema, dict) and (
                    schema.get("custom") == _REQUEST_TYPE_SCHEMA_CUSTOM
                    or schema.get("type") == _REQUEST_TYPE_SCHEMA_TYPE
                ):
                    candidate = str(entry.get("id") or "").strip()
                    if candidate:
                        matched_id = candidate
                        break

            if matched_id is None:
                for entry in payload:
                    if not isinstance(entry, dict) or entry.get("custom") is not True:
                        continue
                    name = str(entry.get("name") or "").strip().lower()
                    if name in _REQUEST_TYPE_FIELD_NAMES:
                        candidate = str(entry.get("id") or "").strip()
                        if candidate:
                            matched_id = candidate
                            break

        self._request_type_field_id = matched_id
        self._request_type_field_resolved = True
        return matched_id

    def _build_search_fields(self) -> str:
        """Return comma-separated JQL search fields including site Request Type ID."""
        request_type_field = self._resolve_request_type_field_id()
        if request_type_field:
            return f"{_BASE_SEARCH_FIELDS},{request_type_field}"
        return _BASE_SEARCH_FIELDS

    def _resolve_request_type_from_fields(self, fields: dict[str, Any]) -> str:
        """Resolve a ticket's request type name from discovered or custom fields."""
        if self._request_type_field_id:
            resolved = _extract_request_type_name(
                fields.get(self._request_type_field_id)
            )
            if resolved:
                return resolved

        default_candidate = _extract_request_type_name(fields.get("customfield_10010"))
        if default_candidate:
            return default_candidate

        for key, val in fields.items():
            if (
                key.startswith("customfield_")
                and isinstance(val, dict)
                and "requestType" in val
            ):
                candidate = _extract_request_type_name(val)
                if candidate:
                    return candidate

        return "Service Request"

    def _resolve_project_key(self, timeout: int = 15) -> str:
        """Resolve and validate a non-empty JSM project key scope."""
        if self.project_key:
            self._resolved_project_key = self.project_key
            return self.project_key
        if self._resolved_project_key:
            return self._resolved_project_key
        if not self.service_desk_id:
            raise ConnectorValidationError(
                "Jira Service Management project_key or service_desk_id is required."
            )
        encoded_desk = quote(self.service_desk_id, safe="")
        try:
            desk = self._get(
                f"/rest/servicedeskapi/servicedesk/{encoded_desk}",
                timeout=timeout,
            )
        except (CredentialInvalidError, InsufficientPermissionsError):
            raise
        except requests.RequestException as e:
            raise ConnectorValidationError(
                f"Failed to resolve JSM service_desk_id '{self.service_desk_id}': {e}"
            ) from e

        resolved = str(desk.get("projectKey") or "").strip()
        if not resolved:
            raise ConnectorValidationError(
                f"Service desk '{self.service_desk_id}' did not return a projectKey."
            )
        self._resolved_project_key = resolved
        return resolved

    def validate_connector_settings(self) -> None:
        """Validate base URL, project/service-desk scope, and API reachability."""
        _normalize_base_url(self.base_url)
        if self.batch_size < 1:
            raise ConnectorValidationError(
                "Jira Service Management batch_size must be at least 1."
            )
        if not self.project_key and not self.service_desk_id:
            raise ConnectorValidationError(
                "Jira Service Management project_key or service_desk_id is required."
            )
        try:
            self._get("/rest/servicedeskapi/info", timeout=15)
            if self.service_desk_id:
                encoded_desk = quote(self.service_desk_id, safe="")
                desk = self._get(
                    f"/rest/servicedeskapi/servicedesk/{encoded_desk}",
                    timeout=15,
                )
                desk_project = str(desk.get("projectKey") or "").strip()
                if not desk_project:
                    raise ConnectorValidationError(
                        f"Service desk '{self.service_desk_id}' has no projectKey."
                    )
                if (
                    self.project_key
                    and desk_project.upper() != self.project_key.upper()
                ):
                    raise ConnectorValidationError(
                        f"Service desk '{self.service_desk_id}' belongs to project "
                        f"'{desk_project}', not '{self.project_key}'."
                    )
                self._resolved_project_key = self.project_key or desk_project
            else:
                encoded_proj = quote(self.project_key, safe="")
                self._get(f"/rest/api/3/project/{encoded_proj}", timeout=15)
                self._resolved_project_key = self.project_key
        except (
            ConnectorValidationError,
            CredentialInvalidError,
            InsufficientPermissionsError,
        ):
            raise
        except requests.RequestException as e:
            raise ConnectorValidationError(
                f"Failed to validate Jira Service Management settings: {e}"
            ) from e

    def _build_jql(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> str:
        """Build a scoped JQL filter using escaped project key and epoch-ms bounds."""
        scoped_project = self._resolve_project_key()
        escaped_key = _escape_jql_string(scoped_project)
        clauses: list[str] = [f'project = "{escaped_key}"']
        if start is not None:
            clauses.append(f"updated >= {math.floor(start * 1000)}")
        if end is not None:
            clauses.append(f"updated <= {math.ceil(end * 1000)}")
        where = " AND ".join(clauses)
        return f"{where} ORDER BY updated ASC"

    def _fetch_issue_comments(
        self,
        issue_key: str,
        comment_field: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        """Return public comments for an issue, excluding internal/restricted notes."""
        field_obj = comment_field or {}
        embedded_raw = field_obj.get("comments") or []
        embedded = [c for c in embedded_raw if isinstance(c, dict)]
        start_at = int(field_obj.get("startAt") or 0)
        total = int(field_obj.get("total") or len(embedded))
        if total == 0 and not embedded:
            return []
        if (
            start_at == 0
            and len(embedded) >= total
            and all(_comment_has_visibility_signal(c) for c in embedded)
        ):
            return [c for c in embedded if _is_public_comment(c)]

        all_comments: list[dict[str, Any]] = []
        offset = 0
        encoded_key = quote(issue_key, safe="")
        while True:
            page = self._get(
                f"/rest/api/3/issue/{encoded_key}/comment",
                params={
                    "startAt": offset,
                    "maxResults": _COMMENT_PAGE_SIZE,
                    "orderBy": "created",
                    "expand": "properties",
                },
                timeout=30,
            )
            raw_items = page.get("comments") or []
            batch = [c for c in raw_items if isinstance(c, dict)]
            all_comments.extend(batch)
            page_total = int(page.get("total") or len(all_comments))
            offset += len(batch)
            if not batch or offset >= page_total:
                break
        return [c for c in all_comments if _is_public_comment(c)]

    def _issue_to_document(self, issue: dict[str, Any]) -> Document:
        """Convert a raw JSM issue dictionary into an Onyx Document."""
        if not isinstance(issue, dict):
            raise TypeError("JSM issue entry must be a JSON object.")
        raw_key = issue.get("key") or issue.get("id")
        if not raw_key:
            raise ValueError("JSM issue entry is missing both 'key' and 'id'.")
        key = str(raw_key)

        raw_fields = issue.get("fields")
        if raw_fields is None or not isinstance(raw_fields, dict):
            raise ValueError(f"JSM issue {key} is missing a valid 'fields' object.")
        fields: dict[str, Any] = raw_fields

        summary = str(fields.get("summary") or key)
        description = fields.get("description") or ""
        if isinstance(description, dict):
            description = self._extract_adf_text(description)
        status_name = str((fields.get("status") or {}).get("name") or "")
        priority_name = str((fields.get("priority") or {}).get("name") or "")
        req_type = self._resolve_request_type_from_fields(fields)

        body_parts = [
            f"Ticket: {key} - {summary}",
            (
                f"Status: {status_name} | Priority: {priority_name} "
                f"| Request Type: {req_type}"
            ),
            f"Description:\n{description}",
        ]
        if self.include_comments:
            raw_comment_field = fields.get("comment")
            comment_field = (
                raw_comment_field if isinstance(raw_comment_field, dict) else None
            )
            comments = self._fetch_issue_comments(key, comment_field)
            for comment in comments:
                c_body = comment.get("body") or ""
                if isinstance(c_body, dict):
                    c_body = self._extract_adf_text(c_body)
                author = ((comment.get("author") or {}).get("displayName")) or "Agent"
                body_parts.append(f"Comment ({author}): {c_body}")

        full_text = "\n\n".join(p for p in body_parts if p.strip())
        normalized_base = _normalize_base_url(self.base_url)
        link = f"{normalized_base}/browse/{key}"
        reporter = fields.get("reporter") or {}
        owners = (
            [
                BasicExpertInfo(
                    display_name=reporter.get("displayName"),
                    email=reporter.get("emailAddress"),
                )
            ]
            if isinstance(reporter, dict) and reporter
            else None
        )
        updated_str = fields.get("updated")
        doc_updated_at = None
        if isinstance(updated_str, str):
            try:
                doc_updated_at = datetime.fromisoformat(updated_str)
            except ValueError:
                pass

        effective_project = self._resolved_project_key or self.project_key
        return Document(
            id=f"jsm:{key}",
            sections=[TextSection(link=link, text=full_text)],
            source=DocumentSource.JIRA_SERVICE_MANAGEMENT,
            semantic_identifier=f"{key}: {summary}",
            doc_updated_at=doc_updated_at,
            primary_owners=owners,
            metadata={
                "ticket_key": key,
                "status": status_name,
                "priority": priority_name,
                "request_type": req_type,
                "project_key": effective_project,
            },
        )

    @classmethod
    def _extract_adf_text(cls, node: dict[str, Any]) -> str:
        """Recursively extract plain text from an Atlassian Document Format node."""
        texts: list[str] = []
        if node.get("type") == "text" and "text" in node:
            texts.append(str(node["text"]))
        texts.extend(
            cls._extract_adf_text(child)
            for child in node.get("content") or []
            if isinstance(child, dict)
        )
        return " ".join(t for t in texts if t).strip()

    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: JSMConnectorCheckpoint,
    ) -> CheckpointOutput[JSMConnectorCheckpoint]:
        """Yield JSM ticket documents for one page and return the updated checkpoint."""
        next_checkpoint = copy.deepcopy(checkpoint)
        jql = self._build_jql(start=start, end=end)
        search_fields = self._build_search_fields()
        params: dict[str, Any] = {
            "jql": jql,
            "maxResults": self.batch_size,
            "fields": search_fields,
        }
        if next_checkpoint.next_page_token:
            params["nextPageToken"] = next_checkpoint.next_page_token

        try:
            payload = self._get("/rest/api/3/search/jql", params=params, timeout=30)
        except requests.HTTPError as e:
            if (
                e.response is not None
                and e.response.status_code == 400
                and self._request_type_field_id
            ):
                self._request_type_field_id = None
                params["fields"] = _BASE_SEARCH_FIELDS
                payload = self._get(
                    "/rest/api/3/search/jql", params=params, timeout=30
                )
            else:
                raise

        issues = payload.get("issues") or []
        seen_keys = set(next_checkpoint.seen_issue_keys)
        normalized_base = _normalize_base_url(self.base_url)

        for issue in issues:
            issue_key = (
                str(issue.get("key") or issue.get("id") or "").strip()
                if isinstance(issue, dict)
                else ""
            )
            raw_fields = issue.get("fields") if isinstance(issue, dict) else None
            issue_updated = (
                str(raw_fields.get("updated") or "").strip()
                if isinstance(raw_fields, dict)
                else ""
            )
            if (
                issue_key
                and issue_key in seen_keys
                and (
                    not issue_updated
                    or next_checkpoint.last_updated_value is None
                    or issue_updated == next_checkpoint.last_updated_value
                )
            ):
                continue
            try:
                doc = self._issue_to_document(issue)
                if issue_key:
                    if (
                        issue_updated
                        and issue_updated != next_checkpoint.last_updated_value
                    ):
                        next_checkpoint.last_updated_value = issue_updated
                        next_checkpoint.seen_issue_keys = [issue_key]
                    else:
                        next_checkpoint.seen_issue_keys.append(issue_key)
                        if (
                            len(next_checkpoint.seen_issue_keys)
                            > _MAX_BOUNDARY_SEEN_KEYS
                        ):
                            next_checkpoint.seen_issue_keys = (
                                next_checkpoint.seen_issue_keys[
                                    -_MAX_BOUNDARY_SEEN_KEYS:
                                ]
                            )
                    seen_keys = set(next_checkpoint.seen_issue_keys)
                yield doc
            except (
                CredentialInvalidError,
                InsufficientPermissionsError,
                requests.RequestException,
            ):
                raise
            except Exception as e:
                if issue_key:
                    yield ConnectorFailure(
                        failed_document=DocumentFailure(
                            document_id=f"jsm:{issue_key}",
                            document_link=f"{normalized_base}/browse/{issue_key}",
                        ),
                        failure_message=f"Failed to parse JSM ticket {issue_key}: {e}",
                        exception=e,
                    )
                else:
                    yield ConnectorFailure(
                        failed_entity=EntityFailure(entity_id="jsm:unknown_issue"),
                        failure_message=f"Failed to parse JSM ticket without key: {e}",
                        exception=e,
                    )

        raw_next_token = payload.get("nextPageToken")
        next_token = str(raw_next_token) if raw_next_token else None
        is_last = payload.get("isLast") is True
        has_more = bool(next_token) and not is_last and len(issues) > 0
        next_checkpoint.next_page_token = next_token if has_more else None
        next_checkpoint.has_more = has_more
        if not has_more:
            next_checkpoint.seen_issue_keys = []
            next_checkpoint.last_updated_value = None
        return next_checkpoint
