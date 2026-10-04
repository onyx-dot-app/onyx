"""Jira Service Management REST helpers.

The JSM REST API (``/rest/servicedeskapi``) is a separate surface from the
Jira platform API the Jira connector uses: service desks are listed there,
issues are searched through the platform API, and each issue's request type
and customer participants live behind JSM endpoints keyed by issue id.

All functions are deliberately transport-level (a ``requests.Session`` plus a
base URL): the connector builds the session, so tests can drive these against
``responses`` without mocking the ``jira`` client objects.
"""

from typing import Any

import requests

from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    InsufficientPermissionsError,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

_JSM_API_PREFIX = "rest/servicedeskapi"
_JSM_PAGE_SIZE = 50
_REQUEST_TIMEOUT = 30


def _jsm_url(jsm_base: str, endpoint: str) -> str:
    """The absolute URL of a JSM API endpoint (endpoint without a leading slash)."""
    return f"{jsm_base.rstrip('/')}/{_JSM_API_PREFIX}/{endpoint.lstrip('/')}"


def build_jsm_session(credentials: dict[str, Any]) -> requests.Session:
    """The session for the JSM REST API, mirroring the Jira connector's
    credential handling: an email + API token is Atlassian Cloud basic auth,
    a bare token is a Data Center personal access token bearer."""
    session = requests.Session()
    if "jira_user_email" in credentials:
        session.auth = (
            credentials["jira_user_email"],
            credentials["jira_api_token"],
        )
    else:
        session.headers["Authorization"] = f"Bearer {credentials['jira_api_token']}"
    session.headers["Accept"] = "application/json"
    session.headers["X-ExperimentalApi"] = "opt-in"
    return session


def _handle_jsm_error(e: requests.RequestException, endpoint: str) -> None:
    """Map HTTP status codes to the connector exception hierarchy."""
    response = e.response
    if response is None:
        return
    status_code = response.status_code
    if status_code == 401:
        raise CredentialExpiredError(
            "Jira Service Management credentials are expired or invalid (HTTP 401)."
        )
    if status_code == 403:
        raise InsufficientPermissionsError(
            f"Insufficient permissions for Jira Service Management endpoint: {endpoint}"
        )
    if status_code == 404:
        raise ConnectorValidationError(
            f"Jira Service Management endpoint not found: {endpoint}. "
            "Check that the base URL points at a Jira Service Management site."
        )


def jsm_get(session: requests.Session, jsm_base: str, endpoint: str) -> dict[str, Any]:
    """GET a JSM endpoint and return the JSON body."""
    url = _jsm_url(jsm_base, endpoint)
    try:
        response = session.get(url, timeout=_REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        _handle_jsm_error(e, endpoint)
        raise


def fetch_service_desks(
    session: requests.Session, jsm_base: str
) -> list[dict[str, Any]]:
    """All service desks the credential can see."""
    desks: list[dict[str, Any]] = []
    start = 0
    while True:
        payload = jsm_get(
            session, jsm_base, f"servicedesk?start={start}&limit={_JSM_PAGE_SIZE}"
        )
        values = payload.get("values", [])
        desks.extend(values)
        if payload.get("isLastPage", True) or not values:
            break
        start += len(values)
    return desks


def fetch_service_desk(
    session: requests.Session, jsm_base: str, desk_id: str
) -> dict[str, Any] | None:
    """One service desk by id, or None when it does not exist / is not
    visible to the credential (404). Auth and permission failures still
    raise so credential problems are not mistaken for a missing desk."""
    try:
        return jsm_get(session, jsm_base, f"servicedesk/{desk_id}")
    except (CredentialExpiredError, InsufficientPermissionsError):
        raise
    except ConnectorValidationError:
        return None


def fetch_request_type_for_issue(
    session: requests.Session, jsm_base: str, issue_id: str
) -> str | None:
    """The request type name of one customer request, best effort: JSM raises
    for non-request issues (e.g. created through the platform API), and those
    are fine to index without a request type."""
    try:
        payload = jsm_get(session, jsm_base, f"request/{issue_id}/requesttype")
    except ConnectorValidationError:
        return None
    except Exception:
        logger.exception(
            "Failed to fetch request type for customer request %s", issue_id
        )
        return None
    # GET request/{id}/requesttype returns the request type as ONE object
    # with a top-level name (not a paged {values: [...]} envelope).
    return payload.get("name") or None


def fetch_participants(
    session: requests.Session, jsm_base: str, issue_id: str
) -> list[dict[str, Any]]:
    """The customer participants of one customer request."""
    try:
        payload = jsm_get(session, jsm_base, f"request/{issue_id}/participant")
    except Exception:
        logger.exception(
            "Failed to fetch participants for customer request %s", issue_id
        )
        return []
    return payload.get("values", [])
