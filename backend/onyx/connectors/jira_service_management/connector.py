from __future__ import annotations

from collections.abc import Generator
from datetime import datetime
from typing import Any

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.miscellaneous_utils import time_str_to_utc
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    InsufficientPermissionsError,
)
from onyx.connectors.interfaces import (
    LoadConnector,
    PollConnector,
    SecondsSinceUnixEpoch,
)
from onyx.connectors.models import (
    ConnectorMissingCredentialError,
    Document,
    TextSection,
)

from .client import JsmApiClient, JsmApiError
from .models import JsmRequest


def _field_value_to_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _to_utc_or_none(date_str: str | None) -> datetime | None:
    if not date_str:
        return None
    try:
        return time_str_to_utc(date_str)
    except Exception:
        return None


def process_jsm_request(
    base_url: str,
    request: JsmRequest,
    comments: list[dict[str, Any]],
    comment_email_blacklist: list[str] | None = None,
) -> Document | None:
    summary = ""
    description = ""
    if request.request_field_values:
        for rfv in request.request_field_values:
            if rfv.name == "Summary":
                summary = _field_value_to_str(rfv.value)
            elif rfv.name == "Description":
                description = _field_value_to_str(rfv.value)

    content_parts: list[str] = []
    if description:
        content_parts.append(description)
    for comment in comments:
        author = comment.get("author") or {}
        author_email = author.get("emailAddress", "")
        if comment_email_blacklist and author_email in comment_email_blacklist:
            continue
        body = comment.get("body") or ""
        if not body.strip():
            continue
        author_name = author.get("displayName", "")
        content_parts.append(f"Comment by {author_name}: {body}")
    content = "\n".join(content_parts)
    if len(content.encode("utf-8")) > 1_000_000:
        return None

    issue_key = request.issue_key or ""
    url = f"{base_url}/browse/{issue_key}"
    reporter_name: str | None = None
    reporter_email: str | None = None
    if request.reporter:
        reporter_name = request.reporter.get("displayName") or request.reporter.get(
            "name"
        )
        reporter_email = request.reporter.get("emailAddress")
    status = request.current_status.get("status") if request.current_status else None
    status_date = (
        request.current_status.get("statusDate") if request.current_status else None
    )

    metadata: dict[str, Any] = {
        "issue_key": issue_key,
        "request_type": request.request_type_id,
        "service_desk_id": request.service_desk_id,
        "status": status,
        "reporter": reporter_name,
        "reporter_email": reporter_email,
        "created": request.created_date,
        "updated": status_date,
    }
    # Drop None values so the metadata validator doesn't stringify them as "None".
    metadata = {k: v for k, v in metadata.items() if v is not None}

    return Document(
        id=url,
        sections=[TextSection(link=url, text=content)],
        source=DocumentSource.JIRA_SERVICE_MANAGEMENT,
        semantic_identifier=f"{issue_key}: {summary}",
        title=f"{issue_key} {summary}",
        doc_updated_at=_to_utc_or_none(status_date),
        doc_created_at=_to_utc_or_none(request.created_date),
        primary_owners=[reporter_name] if reporter_name else None,
        metadata=metadata,
    )


class JiraServiceManagementConnector(LoadConnector, PollConnector):
    def __init__(
        self,
        jira_base_url: str,
        service_desk_id: str | None = None,
        project_key: str | None = None,
        public_comments_only: bool = True,
        comment_email_blacklist: list[str] | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
        scoped_token: bool = False,
    ) -> None:
        self.jira_base_url = jira_base_url
        self.service_desk_id = service_desk_id
        self.project_key = project_key
        self.public_comments_only = public_comments_only
        self.comment_email_blacklist = comment_email_blacklist or []
        self.batch_size = batch_size
        self.scoped_token = scoped_token
        self.client: JsmApiClient | None = None

    def _get_client(self) -> JsmApiClient:
        if self.client is None:
            raise ConnectorMissingCredentialError("Jira Service Management")
        return self.client

    def load_credentials(self, credentials: dict[str, Any]) -> None:
        email = credentials.get("jira_user_email")
        token = credentials.get("jira_api_token")
        if not email or not token:
            raise ConnectorMissingCredentialError("Jira Service Management")
        self.client = JsmApiClient(
            base_url=self.jira_base_url,
            email=email,
            token=token,
        )

    def validate_connector_settings(self) -> None:
        try:
            list(self._get_client().list_service_desks())
        except JsmApiError as e:
            if e.status_code == 401:
                raise CredentialExpiredError("Jira Service Management") from e
            if e.status_code == 403:
                raise InsufficientPermissionsError("Jira Service Management") from e
            if e.status_code == 404:
                raise ConnectorValidationError("Jira Service Management") from e
            raise

    def _iter_request_dicts(self) -> Generator[dict[str, Any], None, None]:
        client = self._get_client()
        if self.service_desk_id:
            yield from client.list_requests(service_desk_id=self.service_desk_id)
            return
        if self.project_key:
            for desk in client.list_service_desks():
                if desk.get("projectKey") == self.project_key:
                    desk_id = desk.get("id")
                    if desk_id is not None:
                        yield from client.list_requests(service_desk_id=desk_id)
            return
        yield from client.list_requests(service_desk_id=None)

    def _doc_for_request(self, req: JsmRequest) -> Document | None:
        if not req.issue_key:
            return None
        comments = list(
            self._get_client().list_comments(
                req.issue_key, public_only=self.public_comments_only
            )
        )
        return process_jsm_request(
            self.jira_base_url,
            req,
            comments,
            comment_email_blacklist=self.comment_email_blacklist,
        )

    def _in_window(
        self, req: JsmRequest, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> bool:
        dates = [req.created_date]
        if req.current_status:
            dates.append(req.current_status.get("statusDate"))
        for date_str in dates:
            if not date_str:
                continue
            try:
                ts = time_str_to_utc(date_str).timestamp()
            except Exception:
                continue
            if start <= ts <= end:
                return True
        return False

    def load_from_state(self) -> Generator[Document, None, None]:
        for req_dict in self._iter_request_dicts():
            doc = self._doc_for_request(JsmRequest(**req_dict))
            if doc is not None:
                yield doc

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> Generator[Document, None, None]:
        for req_dict in self._iter_request_dicts():
            req = JsmRequest(**req_dict)
            if not self._in_window(req, start, end):
                continue
            doc = self._doc_for_request(req)
            if doc is not None:
                yield doc
