from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Any, ClassVar

import requests

from onyx.configs.app_configs import INDEX_BATCH_SIZE, REQUEST_TIMEOUT_SECONDS
from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    InsufficientPermissionsError,
    UnexpectedValidationError,
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

logger = setup_logger()

_JSM_ID_PREFIX = "JSM_REQUEST_"
_JSM_PAGE_LIMIT = 50


def _parse_jsm_datetime(value: Any) -> datetime | None:
    """Parse Jira Service Management date objects or ISO-8601 strings."""
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
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _extract_expert(user_dict: dict[str, Any] | None) -> BasicExpertInfo | None:
    if not isinstance(user_dict, dict):
        return None
    display_name = user_dict.get("displayName") or user_dict.get("name")
    email = user_dict.get("emailAddress")
    if not display_name and not email:
        return None
    return BasicExpertInfo(display_name=display_name, email=email)


class JiraServiceManagementConnector(LoadConnector, PollConnector):
    """Connector for Atlassian Jira Service Management (JSM) REST API (`/rest/servicedeskapi`).

    Indexes service desks, customer requests, request field values, SLA metrics,
    and public/internal comments.
    """

    document_source_type: ClassVar[DocumentSource] = (
        DocumentSource.JIRA_SERVICE_MANAGEMENT
    )

    def __init__(
        self,
        batch_size: int = INDEX_BATCH_SIZE,
        service_desk_ids: str | list[str] | None = None,
        project_key: str | None = None,
        include_internal_comments: bool = True,
    ) -> None:
        self.batch_size = batch_size
        self.include_internal_comments = include_internal_comments
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
            self.service_desk_ids = [str(x).strip() for x in service_desk_ids if str(x).strip()]
        else:
            self.service_desk_ids = None

        self.base_url: str | None = None
        self.user_email: str | None = None
        self.api_token: str | None = None
        self.bearer_token: str | None = None

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        base_url = (
            credentials.get("jsm_base_url")
            or credentials.get("jira_base_url")
            or ""
        )
        user_email = (
            credentials.get("jsm_user_email")
            or credentials.get("jira_user_email")
        )
        api_token = (
            credentials.get("jsm_api_token")
            or credentials.get("jira_api_token")
        )
        bearer_token = credentials.get("jsm_bearer_token") or credentials.get("jira_pat")

        normalized_url = str(base_url).strip().rstrip("/")
        if not normalized_url:
            raise ConnectorMissingCredentialError(
                "Jira Service Management base URL (`jsm_base_url` or `jira_base_url`) is required"
            )
        if not normalized_url.lower().startswith("https://"):
            raise ConnectorValidationError(
                "Jira Service Management base URL must use https://"
            )
        if not bearer_token and not (user_email and api_token):
            raise ConnectorMissingCredentialError(
                "Jira Service Management requires either (`jsm_user_email` + `jsm_api_token`) or `jsm_bearer_token`"
            )

        self.base_url = normalized_url
        self.user_email = str(user_email).strip() if user_email else None
        self.api_token = str(api_token).strip() if api_token else None
        self.bearer_token = str(bearer_token).strip() if bearer_token else None
        return None

    def _api_get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.base_url or (
            not self.bearer_token and not (self.user_email and self.api_token)
        ):
            raise ConnectorMissingCredentialError("jira_service_management")

        url = f"{self.base_url}/rest/servicedeskapi/{path.lstrip('/')}"
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
            response = requests.get(
                url,
                headers=headers,
                auth=auth,
                params=params,
                timeout=REQUEST_TIMEOUT_SECONDS,
                allow_redirects=False,
            )
            response.raise_for_status()
            if response.is_redirect:
                raise UnexpectedValidationError(
                    "Jira Service Management API responded with a redirect "
                    f"(status={response.status_code}); refusing to follow it with credentials."
                )
        except requests.exceptions.HTTPError as e:
            error_response = e.response
            status = error_response.status_code if error_response is not None else None
            body = error_response.text[:500] if error_response is not None else ""
            if status == 401:
                raise CredentialExpiredError(
                    "Invalid or expired Jira Service Management credentials (HTTP 401)."
                ) from e
            if status == 403:
                raise InsufficientPermissionsError(
                    "Insufficient permissions to access Jira Service Management (HTTP 403)."
                ) from e
            raise UnexpectedValidationError(
                f"Unexpected Jira Service Management HTTP error (status={status}): {body}"
            ) from e
        except requests.exceptions.RequestException as e:
            raise UnexpectedValidationError(
                f"Jira Service Management request failed: {e}"
            ) from e

        try:
            data = response.json()
            return data if isinstance(data, dict) else {"values": data}
        except ValueError as e:
            raise UnexpectedValidationError(
                "Invalid JSON returned by Jira Service Management API"
            ) from e

    def _paginate(
        self, path: str, extra_params: dict[str, Any] | None = None
    ) -> Iterator[dict[str, Any]]:
        start_index = 0
        while True:
            params: dict[str, Any] = {"start": start_index, "limit": _JSM_PAGE_LIMIT}
            if extra_params:
                params.update(extra_params)

            payload = self._api_get(path, params=params)
            values = payload.get("values")
            if not isinstance(values, list) or not values:
                break

            for item in values:
                if isinstance(item, dict):
                    yield item

            is_last_page = payload.get("isLastPage")
            if is_last_page is True or len(values) < _JSM_PAGE_LIMIT:
                break
            start_index += len(values)

    def _list_service_desks(self) -> list[dict[str, Any]]:
        desks = list(self._paginate("servicedesk"))
        filtered: list[dict[str, Any]] = []
        for desk in desks:
            desk_id = str(desk.get("id", "")).strip()
            proj_key = str(desk.get("projectKey", "")).strip().upper()
            if self.service_desk_ids is not None and desk_id not in self.service_desk_ids:
                continue
            if self.project_key is not None and proj_key != self.project_key:
                continue
            filtered.append(desk)
        return filtered

    def validate_connector_settings(self) -> None:
        desks = self._list_service_desks()
        if not desks and (
            self.service_desk_ids is not None or self.project_key is not None
        ):
            raise InsufficientPermissionsError(
                "Jira Service Management: the configured service desks or project key "
                "are not visible to this credential."
            )
        if not desks:
            logger.warning(
                "Jira Service Management: no matching service desks visible to this credential."
            )

    def _fetch_request_comments(self, issue_key: str) -> list[dict[str, Any]]:
        # Let failures propagate so a request is never indexed without its comments.
        comments = list(self._paginate(f"request/{issue_key}/comment"))

        if self.include_internal_comments:
            return comments
        return [c for c in comments if bool(c.get("public", True))]

    def _fetch_request_slas(self, issue_key: str) -> list[dict[str, Any]]:
        try:
            return list(self._paginate(f"request/{issue_key}/sla"))
        except Exception as e:
            logger.debug("SLA metrics unavailable for JSM request %s: %s", issue_key, e)
            return []

    def _request_updated_at(self, req: dict[str, Any], comments: list[dict[str, Any]]) -> datetime | None:
        candidates: list[datetime] = []
        created_dt = _parse_jsm_datetime(req.get("createdDate"))
        if created_dt:
            candidates.append(created_dt)

        current_status = req.get("currentStatus")
        if isinstance(current_status, dict):
            status_dt = _parse_jsm_datetime(current_status.get("statusDate"))
            if status_dt:
                candidates.append(status_dt)

        for comment in comments:
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

        links = req.get("_links") if isinstance(req.get("_links"), dict) else {}
        web_link = (
            links.get("web")
            or links.get("agent")
            or f"{self.base_url}/browse/{issue_key}"
        )

        field_values = req.get("requestFieldValues")
        summary = issue_key
        field_lines: list[str] = []
        if isinstance(field_values, list):
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
                    val_str = str(
                        raw_val.get("name")
                        or raw_val.get("value")
                        or raw_val.get("displayName")
                        or raw_val
                    )
                elif isinstance(raw_val, list):
                    val_str = ", ".join(
                        str(
                            v.get("name") or v.get("value") or v
                            if isinstance(v, dict)
                            else v
                        )
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

        current_status = (
            req.get("currentStatus")
            if isinstance(req.get("currentStatus"), dict)
            else {}
        )
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

        if slas:
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
            if sla_lines:
                sections.append(
                    TextSection(
                        link=web_link,
                        text="SLA Metrics:\n" + "\n".join(sla_lines),
                    )
                )

        secondary_owners: list[BasicExpertInfo] = []
        for comment in comments:
            body = str(comment.get("body") or "").strip()
            if not body:
                continue
            author = comment.get("author") if isinstance(comment.get("author"), dict) else None
            author_name = (
                str(author.get("displayName") or author.get("name") or "User")
                if author
                else "User"
            )
            visibility = "Public" if comment.get("public", True) else "Internal"
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

    def _process_requests(
        self, start: datetime | None = None, end: datetime | None = None
    ) -> GenerateDocumentsOutput:
        doc_batch: list[Document | HierarchyNode] = []

        for desk in self._list_service_desks():
            desk_id = desk.get("id")
            extra_params: dict[str, Any] = {}
            if desk_id is not None:
                extra_params["serviceDeskId"] = desk_id

            for req in self._paginate("request", extra_params=extra_params):
                issue_key = str(req.get("issueKey") or req.get("issueId") or "")
                if not issue_key:
                    continue

                comments = self._fetch_request_comments(issue_key)
                updated_at = self._request_updated_at(req, comments)

                if start and updated_at and updated_at < start:
                    continue
                if end and updated_at and updated_at > end:
                    continue

                slas = self._fetch_request_slas(issue_key)
                doc = self._convert_request_to_document(req, desk, comments, slas)
                doc_batch.append(doc)

                if len(doc_batch) >= self.batch_size:
                    yield doc_batch
                    doc_batch = []

        if doc_batch:
            yield doc_batch

    def load_from_state(self) -> GenerateDocumentsOutput:
        return self._process_requests()

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        start_dt = datetime.fromtimestamp(start, tz=timezone.utc)
        end_dt = datetime.fromtimestamp(end, tz=timezone.utc)
        yield from self._process_requests(start=start_dt, end=end_dt)
