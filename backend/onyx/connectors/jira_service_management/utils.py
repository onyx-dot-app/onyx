"""Helpers for the Jira Service Management connector.

The JSM Cloud REST API is rooted at
``https://{your-domain}.atlassian.net/rest/servicedeskapi`` and uses
Atlassian's standard Basic Auth (email + API token) or OAuth 2.0
authentication. We support API-token auth here to mirror how the existing
``onyx.connectors.jira`` connector authenticates against core Jira Cloud,
so a single Atlassian API token works for both connectors.

References:
    https://developer.atlassian.com/cloud/jira/service-desk/rest/intro/
    https://developer.atlassian.com/cloud/jira/service-desk/rest/api-group-request/
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin

import requests
from requests.auth import HTTPBasicAuth

from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    InsufficientPermissionsError,
)
from onyx.connectors.jira_service_management.models import (
    JsmCustomer,
    JsmRequest,
    JsmRequestType,
)

JSM_CLOUD_API_PREFIX = "/rest/servicedeskapi"
DEFAULT_PAGE_SIZE = 50  # JSM caps `limit` at 100; 50 is gentler for low-tier plans
REQUEST_TIMEOUT_SECONDS = 30


def build_jsm_session(domain: str, email: str, api_token: str) -> requests.Session:
    """Build an authenticated requests Session for the JSM REST API."""
    if domain.startswith(("http://", "https://")):
        base_url = domain.rstrip("/")
    else:
        base_url = f"https://{domain}"

    session = requests.Session()
    session.auth = HTTPBasicAuth(email, api_token)
    session.headers.update(
        {
            "Accept": "application/json",
            "X-ExperimentalApi": "opt-in",
        }
    )
    session.base_url = base_url  # type: ignore[attr-defined]
    return session


def jsm_url(session: requests.Session, path: str) -> str:
    base = getattr(session, "base_url", "")
    if not path.startswith("/"):
        path = "/" + path
    return urljoin(base, JSM_CLOUD_API_PREFIX + path)


def jsm_get(session: requests.Session, path: str, **params: Any) -> dict[str, Any]:
    """GET wrapper that normalises common JSM error responses to typed exceptions."""
    response = session.get(
        jsm_url(session, path), params=params or None, timeout=REQUEST_TIMEOUT_SECONDS
    )
    if response.status_code == 401:
        raise CredentialExpiredError(
            "Jira Service Management API token rejected (401)."
        )
    if response.status_code == 403:
        raise InsufficientPermissionsError(
            "API user does not have permission to access this Service Desk (403)."
        )
    if response.status_code == 404:
        raise ConnectorValidationError(
            f"Jira Service Management resource not found: {path}. "
            "Double-check the domain and the service desk ID."
        )
    response.raise_for_status()
    try:
        return response.json()
    except ValueError as e:
        # 200 + HTML (proxy error page, captive portal, ...) — surface as a
        # typed validation error instead of a raw JSONDecodeError.
        raise ConnectorValidationError(
            f"JSM API at {path} returned a non-JSON response: {e}"
        ) from e


# Atlassian emits trailing offsets like ``+0000`` / ``-0500``;
# ``datetime.fromisoformat`` pre-Python 3.11 wants the colon form
# ``+00:00`` / ``-05:00``. Normalise both signs in one pass so negative
# offsets aren't silently dropped to ``ValueError`` (which would force a
# fallback to ``datetime.now(UTC)`` and re-index every poll).
_TRAILING_OFFSET_RE = re.compile(r"([+-])(\d{2})(\d{2})$")


def parse_jsm_datetime(value: Any) -> datetime | None:
    """Parse the ISO-8601 timestamps JSM returns
    (e.g. '2026-05-06T13:45:00.000+0000')."""
    if not value or not isinstance(value, str):
        return None
    cleaned = value.strip().replace("Z", "+00:00")
    cleaned = _TRAILING_OFFSET_RE.sub(r"\1\2:\3", cleaned)
    try:
        parsed = datetime.fromisoformat(cleaned)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        # JSM always returns offsets; a naive stamp must not be interpreted
        # in the host's local timezone (results would drift per deployment).
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _opt_str(value: Any) -> str | None:
    """Pydantic v2 won't coerce e.g. an int accountId to str; normalise here
    so a numerically-typed field degrades to None instead of crashing the sync."""
    return value if isinstance(value, str) and value else None


def _as_dict(value: Any) -> dict[str, Any]:
    """JSM returns explicit JSON nulls for absent fields; `or {}` alone does
    not guard against truthy non-dicts (e.g. a stringified payload)."""
    return value if isinstance(value, dict) else {}


def to_jsm_customer(raw: dict[str, Any] | None) -> JsmCustomer | None:
    if not isinstance(raw, dict):
        return None
    return JsmCustomer(
        account_id=_opt_str(raw.get("accountId")),
        display_name=_opt_str(raw.get("displayName")),
        email=_opt_str(raw.get("emailAddress")),
    )


def to_jsm_request_type(raw: dict[str, Any] | None) -> JsmRequestType | None:
    if not isinstance(raw, dict):
        return None
    return JsmRequestType(
        id=_opt_str(raw.get("id")) or "",
        name=_opt_str(raw.get("name")) or "",
        description=_opt_str(raw.get("description")),
    )


def _derive_updated_at(
    raw: dict[str, Any],
    created_at: datetime,
    resolved_at: datetime | None,
) -> datetime:
    """Best-effort "last touched" timestamp for a JSM request.

    The ``/rest/servicedeskapi/request`` endpoint does **not** return a true
    last-modified timestamp. ``currentStatus.statusDate`` only moves on status
    transitions, so plain description / comment / custom-field edits would
    silently fall through ``poll_source``'s incremental window if we used it
    verbatim. We work around that by taking the most recent of:

    * ``createdDate.iso8601``
    * ``currentStatus.statusDate.iso8601``
    * ``resolutionDate.iso8601``

    That captures creation, status moves and resolutions — the events most
    support workflows care about. Pure description / comment edits on
    already-stable tickets *will* be missed by incremental polls; this is a
    JSM API limitation, documented in the connector's docstring. Full syncs
    (``load_from_state``) still pick those edits up.
    """
    candidates: list[datetime] = [created_at]
    status_dt = parse_jsm_datetime(
        _as_dict(_as_dict(raw.get("currentStatus")).get("statusDate")).get("iso8601")
    )
    if status_dt is not None:
        candidates.append(status_dt)
    if resolved_at is not None:
        candidates.append(resolved_at)
    return max(candidates)


def to_jsm_request(
    raw: dict[str, Any],
    default_service_desk_id: str = "",
    domain: str = "",
) -> JsmRequest:
    """Normalise a raw JSM ``request`` payload to our model.

    Field reference:
    https://developer.atlassian.com/cloud/jira/service-desk/rest/api-group-request/#api-rest-servicedeskapi-request-get

    ``domain`` (e.g. ``acme.atlassian.net``) is used to absolutise the
    portal-relative ``_links.web`` URL JSM returns.
    """
    if not isinstance(raw, dict):
        raise ValueError(f"Expected dict for JSM request payload, got: {type(raw)}")

    issue_key = raw.get("issueKey") or raw.get("referenceString") or ""
    if not isinstance(issue_key, str):
        issue_key = str(issue_key)
    summary = raw.get("summary") or ""
    if not isinstance(summary, str):
        summary = str(summary)
    if not issue_key or not summary:
        raise ValueError(
            "JSM request payload is missing 'issueKey' or 'summary'; "
            f"got keys: {sorted(raw.keys())}"
        )

    # _as_dict (not `.get(key, {})`): JSM returns explicit JSON nulls for
    # absent dates on open requests, and `.get`'s default only fires on
    # missing keys — not on null or non-dict values.
    created_at = parse_jsm_datetime(_as_dict(raw.get("createdDate")).get("iso8601"))
    resolved_at = parse_jsm_datetime(_as_dict(raw.get("resolutionDate")).get("iso8601"))
    if created_at is None:
        raise ValueError(
            f"JSM request {issue_key} has an unparseable/missing createdDate: "
            f"{raw.get('createdDate')}"
        )

    current_status = raw.get("currentStatus")
    if not isinstance(current_status, dict):
        current_status = {}
    status_value = current_status.get("status")
    service_desk_id = str((raw.get("serviceDeskId") or default_service_desk_id or ""))

    links = raw.get("_links")
    if not isinstance(links, dict):
        links = {}
    web_url = links.get("web") or ""
    if web_url and not web_url.startswith(("http://", "https://")):
        # JSM returns portal-relative URLs like "/servicedesk/customer/portal/1/ABC-1"
        web_base = domain.rstrip("/") if domain else ""
        if web_base and not web_base.startswith(("http://", "https://")):
            web_base = f"https://{web_base}"
        web_url = web_base + web_url

    participants_raw = raw.get("participants")
    if not isinstance(participants_raw, list):
        participants_raw = []
    participants = [
        c for c in (to_jsm_customer(p) for p in participants_raw) if c is not None
    ]

    organizations_raw = raw.get("organizations")
    if not isinstance(organizations_raw, dict):
        organizations_raw = {}
    org_values = organizations_raw.get("values")
    if not isinstance(org_values, list):
        org_values = []

    return JsmRequest(
        issue_key=issue_key,
        request_type=to_jsm_request_type(raw.get("requestType")),
        service_desk_id=service_desk_id,
        summary=summary,
        description=_opt_str(raw.get("description")),
        status=status_value
        if isinstance(status_value, str) and status_value
        else "UNKNOWN",
        priority=_opt_str(raw.get("priority")),
        reporter=to_jsm_customer(raw.get("reporter")),
        participants=participants,
        organization_ids=[
            str(o["id"])
            for o in org_values
            if isinstance(o, dict) and o.get("id") is not None
        ],
        created_at=created_at,
        updated_at=_derive_updated_at(raw, created_at, resolved_at),
        resolved_at=resolved_at,
        web_url=web_url,
        raw=raw,
    )
