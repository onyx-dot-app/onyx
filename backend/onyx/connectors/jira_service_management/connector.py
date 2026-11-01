from collections.abc import Iterator
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


@retry_builder(tries=3, delay=1, backoff=2)
def _jsm_get(
    url: str,
    auth: tuple[str, str],
    params: dict[str, Any] | None = None,
) -> requests.Response:
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
        if not self.jsm_base_url.startswith(("http://", "https://")):
            raise ConnectorValidationError(
                "jsm_base_url must start with http:// or https://"
            )
        try:
            _jsm_get(
                f"{self.jsm_base_url}/rest/servicedeskapi/info",
                auth=self._auth,
            )
        except Exception as e:
            raise ConnectorValidationError(
                f"Failed to validate Jira Service Management settings: {e}"
            ) from e

    def _iter_paged(
        self, path: str, params: dict[str, Any] | None = None
    ) -> Iterator[dict[str, Any]]:
        if self._auth is None:
            raise ConnectorMissingCredentialError("Jira Service Management")
        start = 0
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

    def _fetch_comments(self, issue_key: str) -> list[str]:
        comments: list[str] = []
        try:
            for comment in self._iter_paged(
                f"/rest/servicedeskapi/request/{issue_key}/comment"
            ):
                if not comment.get("public", True):
                    continue
                author = (comment.get("author") or {}).get(
                    "displayName", "Participant"
                )
                body = (comment.get("body") or "").strip()
                if body:
                    comments.append(f"{author}: {body}")
        except Exception as e:
            logger.warning(f"Failed to fetch JSM comments for {issue_key}: {e}")
        return comments

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
        updated_dt = _parse_jsm_epoch_ms(status_obj.get("statusDate")) or created_dt

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
        body_parts = [f"Status: {status_name}", *field_lines]

        comments = self._fetch_comments(issue_key)
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
        params: dict[str, Any] = {"expand": "requestFieldValues,currentStatus"}
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
