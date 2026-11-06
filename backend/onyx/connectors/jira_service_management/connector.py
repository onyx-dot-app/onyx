from collections.abc import Iterable, Iterator
from datetime import datetime, timezone
from typing import Any

import requests

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.rate_limit_wrapper import rl_requests
from onyx.connectors.exceptions import ConnectorValidationError
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
    TextSection,
)
from onyx.utils.logger import setup_logger
from onyx.utils.retry_wrapper import retry_builder

logger = setup_logger()

_JSM_PAGE_LIMIT = 50


def _is_transient_jsm_error(exc: BaseException) -> bool:
    if isinstance(exc, requests.HTTPError):
        response = exc.response
        if response is None:
            return False
        return response.status_code == 429 or response.status_code >= 500
    return isinstance(exc, (requests.ConnectionError, requests.Timeout))


@retry_builder(
    tries=3,
    delay=1,
    backoff=2,
    exceptions=(requests.RequestException,),
    retry_if=_is_transient_jsm_error,
)
def _jsm_get(
    url: str,
    auth: tuple[str, str],
    params: dict[str, Any] | None = None,
) -> requests.Response:
    if not url.startswith("https://"):
        raise ConnectorValidationError("jsm_base_url must start with https://")
    response = rl_requests.get(
        url,
        auth=auth,
        params=params,
        headers={"Accept": "application/json"},
        timeout=30,
    )
    response.raise_for_status()
    return response


def _parse_jsm_epoch_ms(raw: dict[str, Any] | None) -> datetime | None:
    if not raw:
        return None
    epoch_ms = raw.get("epochMillis")
    if isinstance(epoch_ms, (int, float)):
        return datetime.fromtimestamp(epoch_ms / 1000.0, tz=timezone.utc)
    iso_str = raw.get("iso8601")
    if isinstance(iso_str, str) and iso_str:
        try:
            return datetime.fromisoformat(iso_str)
        except ValueError:
            return None
    return None


def _extract_sla_lines_and_latest_dt(
    req: dict[str, Any],
) -> tuple[list[str], datetime | None]:
    sla_obj = req.get("sla")
    if isinstance(sla_obj, dict):
        sla_values = sla_obj.get("values") or []
    elif isinstance(sla_obj, list):
        sla_values = sla_obj
    else:
        sla_values = []

    lines: list[str] = []
    latest_dt: datetime | None = None

    def _record_dt(dt: datetime | None) -> None:
        nonlocal latest_dt
        if dt is not None and (latest_dt is None or dt > latest_dt):
            latest_dt = dt

    for metric in sla_values:
        if not isinstance(metric, dict):
            continue
        name = metric.get("name") or str(metric.get("id") or "SLA")
        ongoing = metric.get("ongoingCycle")
        if isinstance(ongoing, dict):
            parts: list[str] = [f"{name} (ongoing)"]
            is_breached = ongoing.get("breached") is True
            for key in ("startTime", "breachTime", "stopTime"):
                dt = _parse_jsm_epoch_ms(ongoing.get(key))
                if key in ("startTime", "stopTime") or (
                    key == "breachTime" and is_breached
                ):
                    _record_dt(dt)
                if dt is not None:
                    parts.append(f"{key}={dt.isoformat()}")
            if "breached" in ongoing:
                parts.append(f"breached={bool(ongoing.get('breached'))}")
            lines.append("SLA " + ", ".join(parts))

        completed_raw = metric.get("completedCycles")
        if isinstance(completed_raw, dict):
            completed_cycles = completed_raw.get("values") or []
        elif isinstance(completed_raw, list):
            completed_cycles = completed_raw
        else:
            completed_cycles = []

        for cycle in completed_cycles:
            if not isinstance(cycle, dict):
                continue
            parts = [f"{name} (completed)"]
            is_breached = cycle.get("breached") is True
            for key in ("startTime", "stopTime", "breachTime"):
                dt = _parse_jsm_epoch_ms(cycle.get(key))
                if key in ("startTime", "stopTime") or (
                    key == "breachTime" and is_breached
                ):
                    _record_dt(dt)
                if dt is not None:
                    parts.append(f"{key}={dt.isoformat()}")
            if "breached" in cycle:
                parts.append(f"breached={bool(cycle.get('breached'))}")
            lines.append("SLA " + ", ".join(parts))

    return lines, latest_dt


class JiraServiceManagementConnector(LoadConnector, PollConnector):
    """Connector for Atlassian Jira Service Management (JSM) REST API
    (`/rest/servicedeskapi`).

    Indexes customer requests, field values, SLA status metrics, and visible
    customer comments across one or all service desks.
    """

    def __init__(
        self,
        jsm_base_url: str,
        service_desk_id: str | None = None,
        request_type_id: str | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
    ) -> None:
        self.jsm_base_url = jsm_base_url.rstrip("/")
        self.service_desk_id = service_desk_id
        self.request_type_id = request_type_id
        self.batch_size = batch_size
        self._auth: tuple[str, str] | None = None

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        email = credentials.get("jira_user_email") or credentials.get("jsm_user_email")
        token = credentials.get("jira_api_token") or credentials.get("jsm_api_token")
        if not isinstance(email, str) or not isinstance(token, str) or not email or not token:
            raise ConnectorMissingCredentialError("Jira Service Management")
        self._auth = (email, token)
        return None

    def validate_connector_settings(self) -> None:
        if self._auth is None:
            raise ConnectorMissingCredentialError("Jira Service Management")
        if not self.jsm_base_url.startswith("https://"):
            raise ConnectorValidationError(
                "jsm_base_url must start with https://"
            )
        if self.request_type_id and not self.service_desk_id:
            raise ConnectorValidationError(
                "request_type_id requires service_desk_id"
            )
        try:
            if self.service_desk_id:
                _jsm_get(
                    f"{self.jsm_base_url}/rest/servicedeskapi/servicedesk/{self.service_desk_id}",
                    auth=self._auth,
                )
            else:
                _jsm_get(
                    f"{self.jsm_base_url}/rest/servicedeskapi/servicedesk",
                    auth=self._auth,
                    params={"start": 0, "limit": 1},
                )
        except Exception as e:
            raise ConnectorValidationError(
                f"Failed to validate Jira Service Management settings: {e}"
            ) from e

    def _iter_paged(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        initial_start: int = 0,
    ) -> Iterator[dict[str, Any]]:
        if self._auth is None:
            raise ConnectorMissingCredentialError("Jira Service Management")
        start = initial_start
        base_params = dict(params or {})
        while True:
            page_params = {**base_params, "start": start, "limit": _JSM_PAGE_LIMIT}
            resp = _jsm_get(
                f"{self.jsm_base_url}{path}",
                auth=self._auth,
                params=page_params,
            )
            payload = resp.json()
            values = payload.get("values") or []
            for item in values:
                yield item
            if payload.get("isLastPage", True) or not values:
                break
            start += len(values)

    def _fetch_comments(
        self,
        issue_key: str,
        embedded_comments: dict[str, Any] | None = None,
    ) -> tuple[list[str], datetime | None]:
        comments: list[str] = []
        latest_comment_dt: datetime | None = None

        def _consume(items: Iterable[dict[str, Any]]) -> None:
            nonlocal latest_comment_dt
            for comment in items:
                if not isinstance(comment, dict):
                    continue
                if comment.get("public") is not True:
                    continue
                comment_dt = _parse_jsm_epoch_ms(
                    comment.get("created") or comment.get("createdDate")
                )
                if comment_dt is not None and (
                    latest_comment_dt is None or comment_dt > latest_comment_dt
                ):
                    latest_comment_dt = comment_dt
                author = (comment.get("author") or {}).get(
                    "displayName", "Participant"
                )
                body = (comment.get("body") or "").strip()
                if body:
                    comments.append(f"{author}: {body}")

        if isinstance(embedded_comments, dict) and isinstance(
            embedded_comments.get("values"), list
        ):
            embedded_values = embedded_comments["values"]
            _consume(embedded_values)
            if not embedded_comments.get("isLastPage", True):
                raw_start = embedded_comments.get("start")
                base_start = raw_start if isinstance(raw_start, int) else 0
                next_start = base_start + len(embedded_values)
                _consume(
                    self._iter_paged(
                        f"/rest/servicedeskapi/request/{issue_key}/comment",
                        initial_start=next_start,
                    )
                )
        else:
            _consume(
                self._iter_paged(
                    f"/rest/servicedeskapi/request/{issue_key}/comment"
                )
            )

        return comments, latest_comment_dt

    def _request_to_document(
        self,
        req: dict[str, Any],
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> Document | None:
        issue_key = req.get("issueKey") or str(req.get("issueId") or "")
        if not issue_key:
            return None

        created_dt = _parse_jsm_epoch_ms(req.get("createdDate"))
        status_obj = req.get("currentStatus") or {}
        status_dt = _parse_jsm_epoch_ms(status_obj.get("statusDate"))
        sla_lines, latest_sla_dt = _extract_sla_lines_and_latest_dt(req)
        embedded_comments = req.get("comments")
        comments, latest_comment_dt = self._fetch_comments(
            issue_key,
            embedded_comments=embedded_comments
            if isinstance(embedded_comments, dict)
            else None,
        )

        activity_candidates = [
            dt
            for dt in (created_dt, status_dt, latest_sla_dt, latest_comment_dt)
            if dt is not None
        ]
        updated_dt = max(activity_candidates) if activity_candidates else None

        if updated_dt is not None:
            ts = updated_dt.timestamp()
            if start is not None and ts < start:
                return None
            if end is not None and ts > end:
                return None

        field_lines: list[str] = []
        summary = issue_key
        for fv in req.get("requestFieldValues") or []:
            label = fv.get("label") or fv.get("fieldId") or "Field"
            val = fv.get("value")
            if isinstance(val, dict):
                val_str = val.get("value") or val.get("name") or str(val)
            elif isinstance(val, list):
                val_str = ", ".join(
                    v.get("value") or v.get("name") or str(v)
                    if isinstance(v, dict)
                    else str(v)
                    for v in val
                )
            else:
                val_str = "" if val is None else str(val)

            if fv.get("fieldId") == "summary" and val_str:
                summary = f"{issue_key}: {val_str}"
            if val_str:
                field_lines.append(f"{label}: {val_str}")

        status_name = status_obj.get("status") or "Unknown"
        body_parts = [f"Status: {status_name}", *field_lines, *sla_lines]

        if comments:
            body_parts.append("Comments:\n" + "\n".join(comments))

        web_link = (req.get("_links") or {}).get(
            "web"
        ) or f"{self.jsm_base_url}/browse/{issue_key}"

        reporter = req.get("reporter") or {}
        owners: list[BasicExpertInfo] = []
        if reporter.get("displayName") or reporter.get("emailAddress"):
            owners.append(
                BasicExpertInfo(
                    display_name=reporter.get("displayName"),
                    email=reporter.get("emailAddress"),
                )
            )

        metadata: dict[str, str | list[str]] = {
            "issue_key": issue_key,
            "status": str(status_name),
        }
        if req.get("serviceDeskId") is not None:
            metadata["service_desk_id"] = str(req["serviceDeskId"])
        if req.get("requestTypeId") is not None:
            metadata["request_type_id"] = str(req["requestTypeId"])
        if sla_lines:
            metadata["sla"] = sla_lines

        return Document(
            id=f"jsm:{self.jsm_base_url}:{issue_key}",
            sections=[TextSection(link=web_link, text="\n".join(body_parts))],
            source=DocumentSource.JIRA_SERVICE_MANAGEMENT,
            semantic_identifier=summary,
            doc_updated_at=updated_dt,
            primary_owners=owners or None,
            metadata=metadata,
        )

    def _generate_documents(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> GenerateDocumentsOutput:
        params: dict[str, Any] = {
            "expand": "sla,comment",
            "requestOwnership": "ALL_REQUESTS",
        }
        if self.service_desk_id:
            params["serviceDeskId"] = self.service_desk_id
        if self.request_type_id:
            params["requestTypeId"] = self.request_type_id

        batch: list[Document] = []
        for req in self._iter_paged("/rest/servicedeskapi/request", params=params):
            doc = self._request_to_document(req, start=start, end=end)
            if doc is not None:
                batch.append(doc)
                if len(batch) >= self.batch_size:
                    yield batch
                    batch = []
        if batch:
            yield batch

    def load_from_state(self) -> GenerateDocumentsOutput:
        yield from self._generate_documents()

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        yield from self._generate_documents(start=start, end=end)
