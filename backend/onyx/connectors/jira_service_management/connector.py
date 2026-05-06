"""Jira Service Management connector for Onyx.

Pulls customer requests from a specified JSM (Service Desk) project and yields
them as ``Document`` objects to be indexed by Onyx. Mirrors the structure of
``onyx.connectors.jira.connector`` but talks to the Service Desk REST API
(``/rest/servicedeskapi``) instead of core Jira's ``/rest/api/3``.

Why a separate connector instead of extending ``JiraConnector``:
    JSM exposes a different domain model (Requests with SLAs, request types,
    participants and organisations) layered on top of issues. Reusing the
    Jira connector would either drop those semantics or pollute the Jira
    connector's surface for non-JSM users. The maintainer
    (https://github.com/onyx-dot-app/onyx/issues/2281#issuecomment-2322316167)
    explicitly asked for a separate connector.

Resolves: https://github.com/onyx-dot-app/onyx/issues/2281
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from datetime import timezone
from typing import Any

from typing_extensions import override

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.jira_service_management.models import JsmRequest
from onyx.connectors.jira_service_management.utils import build_jsm_session
from onyx.connectors.jira_service_management.utils import DEFAULT_PAGE_SIZE
from onyx.connectors.jira_service_management.utils import jsm_get
from onyx.connectors.jira_service_management.utils import to_jsm_request
from onyx.connectors.models import BasicExpertInfo
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import TextSection
from onyx.utils.logger import setup_logger

logger = setup_logger()

_REQUIRED_CREDENTIAL_KEYS = ("jira_user_email", "jira_api_token")


class JiraServiceManagementConnector(LoadConnector, PollConnector):
    """Pulls customer requests from a JSM service-desk project."""

    def __init__(
        self,
        jsm_domain: str,
        service_desk_id: str,
        batch_size: int = INDEX_BATCH_SIZE,
        page_size: int = DEFAULT_PAGE_SIZE,
        request_status: str | None = None,
    ) -> None:
        if not jsm_domain:
            raise ConnectorValidationError("`jsm_domain` is required (e.g. acme.atlassian.net)")
        if not service_desk_id:
            raise ConnectorValidationError(
                "`service_desk_id` is required (find it under Service Desk > Project Settings)"
            )
        self._jsm_domain = jsm_domain
        self._service_desk_id = str(service_desk_id)
        self._batch_size = batch_size
        self._page_size = max(1, min(100, page_size))
        self._request_status = request_status
        self._credentials: dict[str, Any] | None = None

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        missing = [k for k in _REQUIRED_CREDENTIAL_KEYS if k not in credentials]
        if missing:
            raise ConnectorMissingCredentialError(
                f"JSM credentials missing required keys: {', '.join(missing)}"
            )
        self._credentials = credentials
        return None

    def _session(self):
        if self._credentials is None:
            raise ConnectorMissingCredentialError("JSM credentials not loaded")
        return build_jsm_session(
            domain=self._jsm_domain,
            email=self._credentials["jira_user_email"],
            api_token=self._credentials["jira_api_token"],
        )

    def _iter_requests(
        self,
        updated_since: datetime | None = None,
    ) -> Iterable[JsmRequest]:
        """Yield every request in the configured Service Desk that matches the filter."""
        session = self._session()
        start = 0
        while True:
            params: dict[str, Any] = {
                "start": start,
                "limit": self._page_size,
                "serviceDeskId": self._service_desk_id,
            }
            if self._request_status:
                params["requestStatus"] = self._request_status
            payload = jsm_get(session, "/request", **params)
            values = payload.get("values") or []
            if not values:
                break
            for raw in values:
                request = to_jsm_request(raw, default_service_desk_id=self._service_desk_id)
                if updated_since and request.updated_at < updated_since:
                    continue
                yield request
            if payload.get("isLastPage", True):
                break
            start += self._page_size

    @staticmethod
    def _to_document(request: JsmRequest) -> Document:
        primary_owner = (
            BasicExpertInfo(
                display_name=request.reporter.display_name,
                email=request.reporter.email,
            )
            if request.reporter
            else None
        )
        secondary_owners = [
            BasicExpertInfo(display_name=p.display_name, email=p.email)
            for p in request.participants
        ]
        body_parts: list[str] = [request.summary]
        if request.description:
            body_parts.append(request.description)
        text = "\n\n".join(part for part in body_parts if part)
        return Document(
            id=f"jsm:{request.issue_key}",
            sections=[TextSection(link=request.web_url, text=text)],
            source=DocumentSource.JIRA_SERVICE_MANAGEMENT,
            semantic_identifier=f"{request.issue_key} {request.summary}".strip(),
            doc_updated_at=request.updated_at.replace(tzinfo=timezone.utc),
            primary_owners=[primary_owner] if primary_owner else None,
            secondary_owners=secondary_owners or None,
            metadata={
                "issue_key": request.issue_key,
                "service_desk_id": request.service_desk_id,
                "request_type": (request.request_type.name if request.request_type else ""),
                "status": request.status,
                "priority": request.priority or "",
                "organization_ids": ",".join(request.organization_ids),
            },
        )

    def _flush(
        self, batch: list[Document]
    ) -> Iterable[list[Document]]:
        if batch:
            yield batch

    def _yield_in_batches(
        self, requests: Iterable[JsmRequest]
    ) -> GenerateDocumentsOutput:
        batch: list[Document] = []
        for request in requests:
            batch.append(self._to_document(request))
            if len(batch) >= self._batch_size:
                yield batch
                batch = []
        if batch:
            yield batch

    @override
    def load_from_state(self) -> GenerateDocumentsOutput:
        yield from self._yield_in_batches(self._iter_requests())

    @override
    def poll_source(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
    ) -> GenerateDocumentsOutput:
        # JSM does not expose a server-side "updated since" filter on /request,
        # so we paginate the project and filter client-side. Using the connector's
        # poll cadence keeps incremental syncs cheap on small-to-medium service desks.
        updated_since = datetime.fromtimestamp(start, tz=timezone.utc)
        end_dt = datetime.fromtimestamp(end, tz=timezone.utc)
        filtered = (
            r
            for r in self._iter_requests(updated_since=updated_since)
            if r.updated_at <= end_dt
        )
        yield from self._yield_in_batches(filtered)

    def validate_connector_settings(self) -> None:
        # Lightweight validation: hit the service desk metadata endpoint and confirm
        # the configured `service_desk_id` is reachable with the supplied credentials.
        session = self._session()
        jsm_get(session, f"/servicedesk/{self._service_desk_id}")
