from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Any, ClassVar

import requests

from onyx.configs.app_configs import INDEX_BATCH_SIZE, REQUEST_TIMEOUT_SECONDS
from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.rate_limit_wrapper import rl_requests
from onyx.connectors.interfaces import (
    GenerateDocumentsOutput,
    GenerateSlimDocumentOutput,
    LoadConnector,
    PollConnector,
    SecondsSinceUnixEpoch,
    SlimConnector,
)
from onyx.connectors.jira_service_management.models import (
    JSM_ID_PREFIX,
    JsmPollWindow,
    JsmRequestEndpoint,
    JsmTicketRenderContext,
)
from onyx.connectors.jira_service_management.utils import (
    convert_ticket_to_document,
    extract_issue_key,
    is_within_poll_window,
)
from onyx.connectors.models import (
    ConnectorMissingCredentialError,
    Document,
    SlimDocument,
)
from onyx.utils.logger import setup_logger
from onyx.utils.retry_wrapper import retry_builder

logger = setup_logger()

_JSM_PAGE_LIMIT = 50


@retry_builder(tries=3, delay=1, backoff=2)
def _perform_jsm_get(
    endpoint: JsmRequestEndpoint, path_and_params: tuple[str, dict[str, Any]]
) -> requests.Response:
    # Executes a rate-limited HTTP GET against the Jira Service Management REST API.
    path, params = path_and_params
    url = f"{endpoint.base_url.rstrip("/")}/{path.lstrip("/")}"
    response = rl_requests.get(
        url,
        auth=endpoint.auth,
        params=params,
        headers={"Accept": "application/json"},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response


def _fetch_paginated_values(
    endpoint: JsmRequestEndpoint, path_and_params: tuple[str, dict[str, Any]]
) -> Iterator[dict[str, Any]]:
    # Iterates through paginated Jira Service Management REST API responses using start and limit offsets.
    base_path, extra_params = path_and_params
    start = 0
    while True:
        params = {**extra_params, "start": start, "limit": _JSM_PAGE_LIMIT}
        payload = _perform_jsm_get(endpoint, (base_path, params)).json()
        values = payload.get("values") or []
        yield from values
        if payload.get("isLastPage", True) or not values:
            break
        start += len(values)


def _resolve_credential_value(
    credentials: dict[str, Any], candidate_keys: tuple[str, ...]
) -> str | None:
    for key in candidate_keys:
        val = credentials.get(key)
        if val:
            return str(val)
    return None


class JiraServiceManagementConnector(LoadConnector, PollConnector, SlimConnector):
    """Connector for indexing tickets and requests from Jira Service Management projects."""

    document_source_type: ClassVar[DocumentSource] = (
        DocumentSource.JIRA_SERVICE_MANAGEMENT
    )

    def __init__(
        self,
        base_url: str,
        project_key: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.project_key = (
            project_key.strip().upper()
            if project_key and project_key.strip()
            else None
        )
        self.batch_size = INDEX_BATCH_SIZE
        self._auth: tuple[str, str] | None = None

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        email = _resolve_credential_value(
            credentials, ("jira_user_email", "user_email", "username")
        )
        api_token = _resolve_credential_value(
            credentials, ("jira_api_token", "api_token", "password")
        )
        if not email or not api_token:
            raise ConnectorMissingCredentialError(
                "Jira Service Management requires both user email and API token."
            )
        self._auth = (email, api_token)
        return None

    def _require_endpoint(self) -> JsmRequestEndpoint:
        if not self._auth or not self.base_url:
            raise ConnectorMissingCredentialError("jira_service_management")
        return JsmRequestEndpoint(base_url=self.base_url, auth=self._auth)

    def _resolve_service_desk_ids(self, endpoint: JsmRequestEndpoint) -> list[str]:
        if not self.project_key:
            return []
        desks = _fetch_paginated_values(
            endpoint, ("rest/servicedeskapi/servicedesk", {})
        )
        return [
            str(desk["id"])
            for desk in desks
            if str(desk.get("projectKey") or "").upper() == self.project_key
            and desk.get("id") is not None
        ]

    def _fetch_request_comments(
        self, endpoint: JsmRequestEndpoint, issue_key: str
    ) -> list[dict[str, Any]]:
        if not issue_key:
            return []
        try:
            return list(
                _fetch_paginated_values(
                    endpoint,
                    (f"rest/servicedeskapi/request/{issue_key}/comment", {}),
                )
            )
        except Exception:
            logger.warning(
                "Could not fetch comments for JSM request %s", issue_key
            )
            return []

    def _matches_project_and_window(
        self, ticket: dict[str, Any], window: JsmPollWindow
    ) -> bool:
        if not is_within_poll_window(ticket, window):
            return False
        if not self.project_key:
            return True
        issue_key = extract_issue_key(ticket)
        if "-" not in issue_key:
            return True
        return issue_key.split("-", 1)[0].upper() == self.project_key

    def _iter_desk_tickets(
        self,
        endpoint: JsmRequestEndpoint,
        desk_and_window: tuple[str | None, JsmPollWindow],
    ) -> Iterator[dict[str, Any]]:
        desk_id, window = desk_and_window
        extra = {"serviceDeskId": desk_id} if desk_id else {}
        tickets = _fetch_paginated_values(
            endpoint, ("rest/servicedeskapi/request", extra)
        )
        return (
            ticket
            for ticket in tickets
            if self._matches_project_and_window(ticket, window)
        )

    def _iter_all_tickets(
        self, window: JsmPollWindow
    ) -> Iterator[dict[str, Any]]:
        endpoint = self._require_endpoint()
        desk_ids = self._resolve_service_desk_ids(endpoint)
        target_desks: list[str | None] = desk_ids if desk_ids else [None]
        for desk_id in target_desks:
            yield from self._iter_desk_tickets(endpoint, (desk_id, window))

    def _process_tickets(
        self, window: JsmPollWindow
    ) -> GenerateDocumentsOutput:
        endpoint = self._require_endpoint()
        batch: list[Document] = []
        for ticket in self._iter_all_tickets(window):
            issue_key = extract_issue_key(ticket)
            comments = self._fetch_request_comments(endpoint, issue_key)
            ctx = JsmTicketRenderContext(
                base_url=self.base_url,
                default_project_key=self.project_key,
                comments=comments,
            )
            batch.append(convert_ticket_to_document(ticket, ctx))
            if len(batch) >= self.batch_size:
                yield batch
                batch = []
        if batch:
            yield batch

    def load_from_state(self) -> GenerateDocumentsOutput:
        return self._process_tickets(JsmPollWindow())

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        window = JsmPollWindow(
            start=datetime.fromtimestamp(start, tz=timezone.utc),
            end=datetime.fromtimestamp(end, tz=timezone.utc),
        )
        return self._process_tickets(window)

    def retrieve_all_slim_documents(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> GenerateSlimDocumentOutput:
        window = JsmPollWindow(
            start=datetime.fromtimestamp(start, tz=timezone.utc) if start else None,
            end=datetime.fromtimestamp(end, tz=timezone.utc) if end else None,
        )
        batch: list[SlimDocument] = []
        for ticket in self._iter_all_tickets(window):
            issue_key = extract_issue_key(ticket)
            batch.append(SlimDocument(id=f"{JSM_ID_PREFIX}{issue_key}"))
            if len(batch) >= self.batch_size:
                yield batch
                batch = []
        if batch:
            yield batch
