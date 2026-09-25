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

Incremental sync caveat:
    The JSM ``/request`` endpoint does not expose a true "last modified"
    timestamp. ``poll_source`` therefore filters on ``updated_at``, which is
    the most-recent of ``createdDate``, ``currentStatus.statusDate`` and
    ``resolutionDate`` (see ``utils._derive_updated_at``). That captures
    creation, status moves and resolutions — the events most workflows care
    about — but pure description / comment / custom-field edits on
    already-stable tickets are **not** seen by incremental polls. Run
    ``load_from_state`` (full sync) periodically to pick those up, or open
    a follow-up to round-trip to ``/rest/api/3/issue/{key}.fields.updated``
    when the maintainer signals appetite for the extra request volume.

Resolves: https://github.com/onyx-dot-app/onyx/issues/2281
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

import requests
from typing_extensions import override

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.interfaces import (
    GenerateDocumentsOutput,
    LoadConnector,
    PollConnector,
    SecondsSinceUnixEpoch,
)
from onyx.connectors.jira_service_management.models import JsmRequest
from onyx.connectors.jira_service_management.utils import (
    DEFAULT_PAGE_SIZE,
    build_jsm_session,
    jsm_get,
    to_jsm_request,
)
from onyx.connectors.models import (
    BasicExpertInfo,
    ConnectorMissingCredentialError,
    Document,
    TextSection,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

# JSM tickets are backed by the same Atlassian account as core Jira, so the
# credential shape is identical to the existing Jira connector. Users can
# reuse a single API token for both.
_REQUIRED_CREDENTIAL_KEYS = ("jira_user_email", "jira_api_token")


def _safe_utc_fromtimestamp(ts: float, fallback: datetime) -> datetime:
    """datetime.fromtimestamp raises OSError/OverflowError/ValueError for
    NaN, infinities and out-of-range values; poll windows come from the
    scheduler so this is purely defensive."""
    try:
        if not math.isfinite(ts):
            return fallback
        return datetime.fromtimestamp(max(0.0, ts), tz=timezone.utc)
    except (OSError, OverflowError, ValueError):
        return fallback


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
            raise ConnectorValidationError(
                "`jsm_domain` is required (e.g. acme.atlassian.net)"
            )
        # JSM service desk IDs are numeric; rejecting anything else also
        # keeps path-traversal strings ("../..") out of the URL path.
        service_desk_id = str(service_desk_id).strip()
        if not service_desk_id or not service_desk_id.isdigit():
            raise ConnectorValidationError(
                "`service_desk_id` must be the numeric ID of the service desk "
                "(find it under Project Settings, or the number in the portal URL)"
            )
        try:
            page_size = int(page_size)
        except (TypeError, ValueError):
            raise ConnectorValidationError(
                f"`page_size` must be an int, got: {page_size!r}"
            )
        self._jsm_domain = jsm_domain
        self._service_desk_id = service_desk_id
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
        email = credentials["jira_user_email"]
        token = credentials["jira_api_token"]
        # BasicAuth would otherwise happily send a literal "None" username and
        # surface later as a misleading 401 "token rejected".
        if not isinstance(email, str) or not email.strip():
            raise ConnectorMissingCredentialError(
                "jira_user_email must be a non-empty string"
            )
        if not isinstance(token, str) or not token.strip():
            raise ConnectorMissingCredentialError(
                "jira_api_token must be a non-empty string"
            )
        self._credentials = credentials
        return None

    def _session(self) -> requests.Session:
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
        """Yield every request in the configured Service Desk that matches the filter.

        Paginates via ``start``/``limit`` until ``isLastPage`` (or an empty
        page, which some JSM versions return instead). ``start`` is advanced
        by the number of values actually received, not by ``page_size``, so
        a short page produced by server-side filtering cannot desync the
        cursor.

        A server (or a caching proxy) that ignores ``start`` and keeps
        replaying the first page would otherwise loop forever, so a page
        whose issue keys were all already yielded terminates pagination.
        """
        session = self._session()
        start = 0
        seen_issue_keys: set[str] = set()
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
            page_keys = {
                str(v.get("issueKey") or "") for v in values if isinstance(v, dict)
            }
            if page_keys and page_keys.issubset(seen_issue_keys):
                logger.warning(
                    "JSM pagination returned an all-duplicate page (start=%s) — "
                    "the server appears to be ignoring the cursor. Stopping.",
                    start,
                )
                break
            seen_issue_keys |= page_keys
            for raw in values:
                try:
                    request = to_jsm_request(
                        raw,
                        default_service_desk_id=self._service_desk_id,
                        domain=self._jsm_domain,
                    )
                except Exception:
                    # One malformed ticket must not kill the whole sync;
                    # the rest of the page still indexes.
                    logger.exception(
                        "Skipping unparseable JSM request payload: %s", raw
                    )
                    continue
                if updated_since and request.updated_at < updated_since:
                    continue
                yield request
            is_last_page = payload.get("isLastPage", True)
            if isinstance(is_last_page, str):
                is_last_page = is_last_page.strip().lower() == "true"
            if is_last_page:
                break
            start += len(values)

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
            id=request.web_url or f"jsm:{request.issue_key}",
            sections=[TextSection(link=request.web_url or None, text=text)],
            source=DocumentSource.JIRA_SERVICE_MANAGEMENT,
            semantic_identifier=f"{request.issue_key} {request.summary}".strip(),
            doc_updated_at=request.updated_at,
            doc_created_at=request.created_at,
            primary_owners=[primary_owner] if primary_owner else None,
            secondary_owners=secondary_owners or None,
            metadata={
                "issue_key": request.issue_key,
                "service_desk_id": request.service_desk_id,
                "request_type": (
                    request.request_type.name if request.request_type else ""
                ),
                "status": request.status,
                "priority": request.priority or "",
                "organization_ids": ",".join(request.organization_ids),
            },
        )

    def _yield_in_batches(
        self, jsm_requests: Iterable[JsmRequest]
    ) -> GenerateDocumentsOutput:
        batch: list[Document] = []
        for request in jsm_requests:
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
        updated_since = _safe_utc_fromtimestamp(
            start, datetime.min.replace(tzinfo=timezone.utc)
        )
        end_dt = _safe_utc_fromtimestamp(end, datetime.max.replace(tzinfo=timezone.utc))
        filtered = (
            r
            for r in self._iter_requests(updated_since=updated_since)
            if r.updated_at <= end_dt
        )
        yield from self._yield_in_batches(filtered)

    @override
    def validate_connector_settings(self) -> None:
        # Lightweight validation: hit the service desk metadata endpoint and
        # confirm the configured `service_desk_id` is reachable with the
        # supplied credentials. jsm_get maps 401/403/404 to typed exceptions,
        # surface those instead of swallowing them.
        session = self._session()
        jsm_get(session, f"/servicedesk/{self._service_desk_id}")
