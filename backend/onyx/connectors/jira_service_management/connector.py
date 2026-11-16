"""Jira Service Management (JSM) connector.

Indexes customer requests ("tickets") from one JSM service desk — or from
every desk the credential can read when no desk is configured. Each request
becomes one document: summary + description + public comments.

Scope note: JSM-specific REST surface (`/rest/servicedeskapi/...`), not JQL.
The existing `jira` connector already covers Jira Software issue search;
this connector exists because JSM requests (portal tickets) are a different
API family with different objects (service desks, request types, customer
comments).
"""

import time
from collections.abc import Callable
from typing import Any

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.miscellaneous_utils import (
    time_str_to_utc,
)
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
from onyx.connectors.jira_service_management.client import (
    JsmApiClient,
    JsmClientRequestFailedError,
)
from onyx.connectors.models import (
    ConnectorMissingCredentialError,
    Document,
    TextSection,
)

_DESCRIPTION_KEY = "description"
_SUMMARY_KEY = "summary"
# JSM request payloads carry custom fields; only these two well-known
# requestFieldValues entries become document text.
_KNOWN_TEXT_FIELDS = {_SUMMARY_KEY, _DESCRIPTION_KEY}


def _field_value_text(request: dict[str, Any], key: str) -> str:
    value = (request.get("requestFieldValues") or {}).get(key)
    if not isinstance(value, dict):
        return ""
    text = value.get("value")
    return str(text).strip() if text is not None else ""


class JiraServiceManagementConnector(LoadConnector, PollConnector):
    """Connector for Jira Service Management. Implements LoadConnector for
    the initial backfill and PollConnector for incremental updates."""

    def __init__(
        self,
        service_desk_id: str | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
        include_attachments: bool = False,
    ) -> None:
        self.service_desk_id = service_desk_id or None
        self.batch_size = batch_size
        # No attachment enumeration in v1; the flag exists per the shared
        # convention and must gate any future attachment path.
        self.include_attachments = include_attachments
        self.jsm_client: JsmApiClient | None = None

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        required_keys = [
            "jira_service_management_base_url",
            "jira_service_management_email",
            "jira_service_management_api_token",
        ]
        for key in required_keys:
            if not credentials.get(key):
                raise ConnectorMissingCredentialError("Jira Service Management")

        self.jsm_client = JsmApiClient(
            base_url=credentials["jira_service_management_base_url"],
            email=credentials["jira_service_management_email"],
            api_token=credentials["jira_service_management_api_token"],
        )
        return None

    def _request_to_document(self, request: dict[str, Any]) -> Document | None:
        client = self.jsm_client
        if client is None:
            raise ConnectorMissingCredentialError("Jira Service Management")

        issue_key = str(request.get("issueKey") or request.get("issueId") or "")
        if not issue_key:
            return None

        summary = _field_value_text(request, _SUMMARY_KEY) or str(
            request.get("summary") or ""
        )
        description = _field_value_text(request, _DESCRIPTION_KEY)

        comments = client.list_request_comments(issue_key, self.batch_size)
        comment_texts = []
        for comment in comments:
            body = comment.get("body")
            if isinstance(body, str) and body.strip():
                comment_texts.append(body.strip())

        text_parts = [part for part in [summary, description] if part]
        text_parts.extend(comment_texts)
        text = "\n".join(text_parts).strip()
        if not text:
            # Skip entirely empty requests; nothing to embed.
            return None

        status = ((request.get("currentStatus") or {}).get("status")) or ""
        reporter = ((request.get("reporter") or {}).get("displayName")) or ""
        service_desk_id = str(request.get("serviceDeskId") or "")
        request_type_id = str(request.get("requestTypeId") or "")

        created_at = (request.get("createdDate") or {}).get("iso8601")
        updated_at = (request.get("currentStatus") or {}).get("statusDate", {}).get(
            "iso8601"
        ) or created_at

        return Document(
            id=f"jira_service_management__{issue_key}",
            sections=[
                TextSection(
                    link=f"{client.base_url}/browse/{issue_key}",
                    text=text,
                )
            ],
            source=DocumentSource.JIRA_SERVICE_MANAGEMENT,
            semantic_identifier=(f"{issue_key}: {summary}" if summary else issue_key),
            title=summary or issue_key,
            doc_updated_at=time_str_to_utc(updated_at) if updated_at else None,
            doc_created_at=time_str_to_utc(created_at) if created_at else None,
            metadata={
                "issue_key": issue_key,
                "service_desk_id": service_desk_id,
                "request_type_id": request_type_id,
                "status": status,
                "reporter": reporter,
            },
        )

    def _iter_desks(self) -> list[str]:
        client = self.jsm_client
        if client is None:
            raise ConnectorMissingCredentialError("Jira Service Management")
        if self.service_desk_id:
            return [self.service_desk_id]
        desks = client.list_service_desks(self.batch_size)
        return [str(desk["id"]) for desk in desks if desk.get("id") is not None]

    def _fetch_documents(
        self, time_filter: Callable[[Document], bool] | None = None
    ) -> GenerateDocumentsOutput:
        for desk_id in self._iter_desks():
            requests_page = self.jsm_client.list_requests(  # type: ignore[union-attr]
                desk_id, self.batch_size
            )
            batch: list[Document] = []
            for request in requests_page:
                document = self._request_to_document(request)
                if document is None:
                    continue
                if time_filter is not None and not time_filter(document):
                    continue
                batch.append(document)
                if len(batch) >= self.batch_size:
                    yield batch
                    batch = []
                    time.sleep(0.2)
            if batch:
                yield batch

    def load_from_state(self) -> GenerateDocumentsOutput:
        if self.jsm_client is None:
            raise ConnectorMissingCredentialError("Jira Service Management")
        return self._fetch_documents()

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        if self.jsm_client is None:
            raise ConnectorMissingCredentialError("Jira Service Management")

        # The JSM request list endpoint has no updated-since parameter, so
        # poll filters client-side on the status/created timestamps.
        def time_filter(doc: Document) -> bool:
            if doc.doc_updated_at is None:
                return False
            doc_timestamp = doc.doc_updated_at.timestamp()
            return start <= doc_timestamp <= end

        return self._fetch_documents(time_filter)

    def validate_connector_settings(self) -> None:
        if self.jsm_client is None:
            raise ConnectorMissingCredentialError("Jira Service Management")
        try:
            # One-page desk listing doubles as the auth probe.
            self.jsm_client.list_service_desks(page_size=1)
            if self.service_desk_id:
                # Confirm the configured desk exists and is readable.
                self.jsm_client.list_requests(self.service_desk_id, page_size=1)
        except JsmClientRequestFailedError as e:
            if e.status_code == 401:
                raise CredentialExpiredError(
                    "Your Jira Service Management credentials appear to be "
                    "invalid or expired (HTTP 401)."
                ) from e
            if e.status_code == 403:
                raise InsufficientPermissionsError(
                    "The configured Jira Service Management token does not "
                    "have sufficient permissions (HTTP 403)."
                ) from e
            if e.status_code == 404:
                raise ConnectorValidationError(
                    f"Service desk {self.service_desk_id} was not found (HTTP 404)."
                ) from e
            raise ConnectorValidationError(
                f"Unexpected Jira Service Management error "
                f"(status={e.status_code}): {e}"
            ) from e
        except Exception as exc:
            raise ConnectorValidationError(
                "Unexpected error while validating Jira Service Management "
                f"connector settings: {exc}"
            ) from exc
