"""Utility functions for the Jira Service Management connector."""

import requests
from requests.auth import HTTPBasicAuth
from typing import Any

from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.utils.logger import setup_logger

logger = setup_logger()

JSM_API_PATH = "rest/servicedeskapi"

# Known name patterns for JSM SLA fields (case-insensitive substring match)
_SLA_FIELD_PATTERNS = {
    "sla_time_to_first_response": ["time to first response"],
    "sla_time_to_resolution": ["time to resolution", "time to resolve"],
}


def build_jsm_session(credentials: dict[str, Any], jira_base: str) -> requests.Session:
    """Build a requests.Session configured for JSM API calls.

    Authentication mirrors the existing Jira connector:
    - Cloud: email + API token (Basic auth)
    - Server/Data Center: personal access token (Bearer)
    """
    api_token: str = credentials.get("jira_api_token", "")
    if not api_token:
        raise ConnectorMissingCredentialError("jira_api_token is required")

    session = requests.Session()
    is_cloud = "jira_user_email" in credentials

    if is_cloud:
        email = credentials["jira_user_email"]
        session.auth = HTTPBasicAuth(email, api_token)
    else:
        session.headers.update({"Authorization": f"Bearer {api_token}"})

    session.headers.update(
        {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-ExperimentalApi": "opt-in",
        }
    )
    return session


def get_service_desks(
    session: requests.Session, jira_base: str
) -> list[dict[str, Any]]:
    """Retrieve all service desks accessible to the authenticated user."""
    url = f"{jira_base.rstrip('/')}/{JSM_API_PATH}/servicedesk"
    service_desks: list[dict[str, Any]] = []
    start = 0
    limit = 50

    while True:
        resp = session.get(url, params={"start": start, "limit": limit})
        resp.raise_for_status()
        data = resp.json()
        values = data.get("values", [])
        service_desks.extend(values)
        if data.get("isLastPage", True):
            break
        start += limit

    return service_desks


def discover_sla_field_ids(
    session: requests.Session, jira_base: str
) -> dict[str, str]:
    """Discover JSM SLA custom field IDs dynamically via the Jira fields API.

    SLA custom field IDs (e.g. customfield_10020) are assigned per-instance
    during project setup and are NOT universal. This function queries
    GET /rest/api/2/field and matches against known SLA field name patterns.

    Returns a dict mapping our label keys to their customfield_* keys.
    e.g. {"sla_time_to_first_response": "customfield_10020", ...}
    """
    url = f"{jira_base.rstrip('/')}/rest/api/2/field"
    try:
        resp = session.get(url, timeout=10)
        resp.raise_for_status()
        fields = resp.json()
    except Exception as e:
        logger.warning(f"Could not discover JSM SLA field IDs: {e}")
        return {}

    result: dict[str, str] = {}
    for field in fields:
        field_id = field.get("id", "")
        field_name = (field.get("name") or "").lower()
        if not field_id.startswith("customfield_"):
            continue
        for label, patterns in _SLA_FIELD_PATTERNS.items():
            if label not in result and any(p in field_name for p in patterns):
                result[label] = field_id

    if result:
        logger.debug(f"Discovered SLA field IDs: {result}")
    else:
        logger.warning(
            "No SLA custom fields found via Jira fields API. "
            "SLA metadata will not be extracted."
        )
    return result


def extract_jsm_metadata(
    issue: Any,
    sla_field_ids: dict[str, str],
) -> dict[str, str | list[str]]:
    """Extract JSM-specific metadata from a Jira issue.

    Args:
        issue: A jira.resources.Issue object.
        sla_field_ids: Mapping of label → customfield_* key, as returned
                       by discover_sla_field_ids().
    """
    metadata: dict[str, str | list[str]] = {}

    try:
        fields = issue.raw.get("fields", {})

        # Request type (JSM-specific issue type)
        request_type = fields.get("issuetype", {})
        if isinstance(request_type, dict) and request_type.get("name"):
            metadata["request_type"] = request_type["name"]

        # SLA fields — discovered dynamically to avoid hardcoded IDs
        for label, field_key in sla_field_ids.items():
            sla_field = fields.get(field_key)
            if not sla_field or not isinstance(sla_field, dict):
                continue
            completed = sla_field.get("completedCycles", [])
            ongoing = sla_field.get("ongoingCycle", {})
            if completed:
                metadata[label] = "breached" if completed[-1].get("breached") else "met"
            elif ongoing:
                metadata[label] = "breached" if ongoing.get("breached") else "ongoing"

        # Customer request type (portal-facing label)
        customer_request = fields.get("customfield_10010")
        if customer_request and isinstance(customer_request, dict):
            rt = customer_request.get("requestType", {})
            if isinstance(rt, dict) and rt.get("name"):
                metadata["customer_request_type"] = rt["name"]

        # Priority
        priority = fields.get("priority", {})
        if isinstance(priority, dict) and priority.get("name"):
            metadata["priority"] = priority["name"]

        # Status category
        status = fields.get("status", {})
        if isinstance(status, dict):
            status_category = status.get("statusCategory", {})
            if isinstance(status_category, dict) and status_category.get("name"):
                metadata["status_category"] = status_category["name"]

    except Exception as e:
        logger.warning(f"Error extracting JSM metadata: {e}")

    return metadata
