"""Helpers for the Jira Service Management connector.

The JSM Cloud REST API is rooted at ``https://{your-domain}.atlassian.net/rest/servicedeskapi``
and uses Atlassian's standard Basic Auth (email + API token) or OAuth 2.0
authentication. We support API-token auth here to mirror how the existing
``onyx.connectors.jira`` connector authenticates against core Jira Cloud.
"""

from __future__ import annotations

from datetime import datetime
from datetime import timezone
from typing import Any
from urllib.parse import urljoin

import requests
from requests.auth import HTTPBasicAuth

from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.exceptions import CredentialExpiredError
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.jira_service_management.models import JsmCustomer
from onyx.connectors.jira_service_management.models import JsmRequest
from onyx.connectors.jira_service_management.models import JsmRequestType

JSM_CLOUD_API_PREFIX = "/rest/servicedeskapi"
DEFAULT_PAGE_SIZE = 50  # JSM caps `limit` at 100; 50 is gentler for low-tier plans
REQUEST_TIMEOUT_SECONDS = 30


def build_jsm_session(domain: str, email: str, api_token: str) -> requests.Session:
    """Build an authenticated requests Session for the JSM REST API."""
    if not domain.startswith(("http://", "https://")):
        base_url = f"https://{domain}"
    else:
        base_url = domain.rstrip("/")
    session = requests.Session()
    session.auth = HTTPBasicAuth(email, api_token)
    session.headers.update(
        {
            "Accept": "application/json",
            "Content-Type": "application/json",
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
        raise CredentialExpiredError("Jira Service Management API token rejected (401).")
    if response.status_code == 403:
        raise InsufficientPermissionsError(
            "API user does not have permission to access this Service Desk (403)."
        )
    if response.status_code == 404:
        raise ConnectorValidationError(
            f"Jira Service Management resource not found: {path}"
        )
    response.raise_for_status()
    return response.json()


def parse_jsm_datetime(value: Any) -> datetime | None:
    """Parse the ISO-8601 timestamps JSM returns (e.g. '2026-05-06T13:45:00.000+0000')."""
    if not value or not isinstance(value, str):
        return None
    cleaned = value.replace("Z", "+00:00")
    if "+" in cleaned[10:] and len(cleaned) >= 5 and cleaned[-5] in ("+", "-"):
        cleaned = cleaned[:-2] + ":" + cleaned[-2:]
    try:
        return datetime.fromisoformat(cleaned).astimezone(timezone.utc)
    except ValueError:
        return None


def to_jsm_customer(raw: dict[str, Any] | None) -> JsmCustomer | None:
    if not raw:
        return None
    return JsmCustomer(
        account_id=raw.get("accountId"),
        display_name=raw.get("displayName"),
        email=raw.get("emailAddress"),
    )


def to_jsm_request_type(raw: dict[str, Any] | None) -> JsmRequestType | None:
    if not raw:
        return None
    return JsmRequestType(
        id=str(raw.get("id", "")),
        name=raw.get("name", ""),
        description=raw.get("description"),
    )


def to_jsm_request(raw: dict[str, Any], default_service_desk_id: str = "") -> JsmRequest:
    """Normalise a raw JSM ``request`` payload to our ``JsmRequest`` model."""
    fields = raw.get("requestFieldValues") or []
    field_map = {f.get("fieldId"): f for f in fields}
    summary = (field_map.get("summary") or {}).get("value") or raw.get("summary") or ""
    description = (field_map.get("description") or {}).get("value")
    current_status = raw.get("currentStatus") or {}
    return JsmRequest(
        issue_key=raw.get("issueKey", ""),
        request_type=to_jsm_request_type(raw.get("requestType")),
        service_desk_id=str(raw.get("serviceDeskId") or default_service_desk_id),
        summary=str(summary)[:1024],
        description=str(description) if description else None,
        status=str(current_status.get("status") or ""),
        priority=str(((field_map.get("priority") or {}).get("value") or {}).get("name") or "")
        or None,
        reporter=to_jsm_customer(raw.get("reporter")),
        participants=[
            c
            for c in (to_jsm_customer(p) for p in raw.get("requestParticipants") or [])
            if c is not None
        ],
        organization_ids=[
            str(o.get("id"))
            for o in raw.get("requestParticipantOrganizations") or []
            if o.get("id")
        ],
        created_at=parse_jsm_datetime(raw.get("createdDate", {}).get("iso8601"))
        or datetime.now(timezone.utc),
        updated_at=parse_jsm_datetime(raw.get("currentStatus", {}).get("statusDate", {}).get("iso8601"))
        or datetime.now(timezone.utc),
        resolved_at=parse_jsm_datetime((raw.get("resolutionDate") or {}).get("iso8601")),
        web_url=(raw.get("_links") or {}).get("web", ""),
        raw=raw,
    )
