"""Helpers for the Jira Service Management (JSM) customer-facing REST API.

The `jira` Python library does not wrap `rest/servicedeskapi`, so these helpers
call it through the authenticated session of an existing `JIRA` client.
JSM requests are Jira issues under the hood, so issue fetching stays on the
standard JQL path and this module only adds service-desk-specific data.
"""

from typing import Any

from jira import JIRA

from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    InsufficientPermissionsError,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

_SERVICE_DESK_API = "rest/servicedeskapi"
_SERVICE_DESK_PAGE_SIZE = 50


def _handle_jsm_api_error(e: Exception, context: str) -> None:
    status_code = getattr(e, "response", None)  # ods: ignore[getattr]
    status = (
        e.response.status_code  # ty: ignore[unresolved-attribute]
        if status_code is not None
        else getattr(e, "status_code", None)  # ods: ignore[getattr]
    )
    if status == 401:
        raise CredentialExpiredError(
            "Jira Service Management credentials are expired or invalid (HTTP 401)."
        )
    if status == 403:
        raise InsufficientPermissionsError(
            f"Insufficient permissions for Jira Service Management API. Context: {context}"
        )
    if status == 404:
        raise ConnectorValidationError(
            f"Jira Service Management resource not found. Context: {context}"
        )
    raise e


def service_desk_api_get(
    jira_client: JIRA, path: str, params: dict[str, Any] | None = None
) -> dict[str, Any]:
    """GET a `rest/servicedeskapi` resource using the JIRA client's session."""
    server = jira_client._options["server"]
    url = f"{server}/{_SERVICE_DESK_API}/{path}"
    try:
        response = jira_client._session.get(  # ty: ignore[unresolved-attribute]
            url, params=params
        )
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict):
            raise ConnectorValidationError(
                f"Unexpected Jira Service Management API response at {path}"
            )
        return result
    except ConnectorValidationError:
        raise
    except Exception as e:
        _handle_jsm_api_error(e, path)
        raise  # unreachable, for the type checker


def list_service_desks(jira_client: JIRA) -> list[dict[str, Any]]:
    """Return all service desks visible to the credentials."""
    desks: list[dict[str, Any]] = []
    start = 0
    while True:
        data = service_desk_api_get(
            jira_client,
            "servicedesk",
            params={"start": start, "limit": _SERVICE_DESK_PAGE_SIZE},
        )
        values = data.get("values", [])
        desks.extend(values)
        if data.get("isLastPage", True) or not values:
            return desks
        start += len(values)


def find_service_desk(
    jira_client: JIRA,
    service_desk_id: int | None = None,
    project_key: str | None = None,
) -> dict[str, Any] | None:
    """Resolve a service desk by id or by its backing project key."""
    if service_desk_id is not None:
        try:
            return service_desk_api_get(jira_client, f"servicedesk/{service_desk_id}")
        except (CredentialExpiredError, InsufficientPermissionsError):
            raise
        except ConnectorValidationError:
            return None

    if project_key:
        for desk in list_service_desks(jira_client):
            if desk.get("projectKey") == project_key:
                return desk
    return None


def get_customer_request(jira_client: JIRA, issue_key: str) -> dict[str, Any] | None:
    """Fetch the JSM customer request view of an issue.

    Returns None when the issue is not exposed as a customer request
    (e.g. internal-only tickets).
    """
    try:
        return service_desk_api_get(
            jira_client,
            f"request/{issue_key}",
            params={"expand": "requestType,currentStatus"},
        )
    except (CredentialExpiredError, InsufficientPermissionsError):
        raise
    except ConnectorValidationError:
        return None


def build_customer_portal_url(
    jira_base_url: str, service_desk_id: int | str | None, issue_key: str
) -> str | None:
    """Customer portal URL, e.g. `<base>/servicedesk/customer/portal/3/HELP-42`."""
    if service_desk_id is None:
        return None
    return f"{jira_base_url}/servicedesk/customer/portal/{service_desk_id}/{issue_key}"


def get_request_type_name(request: dict[str, Any] | None) -> str | None:
    if not request:
        return None
    request_type = request.get("requestType")
    if isinstance(request_type, dict):
        name = request_type.get("name")
        return name if isinstance(name, str) else None
    return None


def get_current_status_name(request: dict[str, Any] | None) -> str | None:
    """Customer-visible status, which can differ from the workflow status."""
    if not request:
        return None
    current_status = request.get("currentStatus")
    if isinstance(current_status, dict):
        status = current_status.get("status")
        return status if isinstance(status, str) else None
    return None
