"""Utility functions for the Jira Service Management connector."""

import requests
from requests.auth import HTTPBasicAuth
from typing import Any

from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.utils.logger import setup_logger

logger = setup_logger()

JSM_API_PATH = "rest/servicedeskapi"

# Known name patterns for JSM custom fields (case-insensitive substring match).
# Field IDs are assigned per-instance so we discover them dynamically.
_CUSTOM_FIELD_PATTERNS = {
    "sla_time_to_first_response": ["time to first response"],
    "sla_time_to_resolution": ["time to resolution", "time to resolve"],
    "customer_request_type": ["customer request type", "portal request type"],
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
    is_cloud = bool(credentials.get("jira_user_email"))

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
        resp = session.get(url, params={"start": start, "limit": limit}, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        values = data.get("values", [])
        service_desks.extend(values)
        if data.get("isLastPage", True):
            break
        start += limit

    return service_desks


def discover_jsm_custom_field_ids(
    session: requests.Session, jira_base: str
) -> dict[str, str]:
    """Discover JSM custom field IDs dynamically via the Jira fields API.

    Custom field IDs (e.g. customfield_10020) are assigned per-instance
    during project setup and are NOT universal. This function queries
    GET /rest/api/2/field and matches against known field name patterns.

    Returns a dict mapping our label keys to their customfield_* keys.
    e.g. {"sla_time_to_first_response": "customfield_10020", ...}
    """
    url = f"{jira_base.rstrip('/')}/rest/api/2/field"
    try:
        resp = session.get(url, timeout=10)
        resp.raise_for_status()
        fields = resp.json()
    except Exception as e:
        logger.warning(f"Could not discover JSM custom field IDs: {e}")
        return {}

    result: dict[str, str] = {}
    for field in fields:
        field_id = field.get("id", "")
        field_name = (field.get("name") or "").lower()
        if not field_id.startswith("customfield_"):
            continue
        for label, patterns in _CUSTOM_FIELD_PATTERNS.items():
            if label not in result and any(p in field_name for p in patterns):
                result[label] = field_id

    if result:
        logger.debug(f"Discovered JSM custom field IDs: {result}")
    else:
        logger.warning(
            "No JSM custom fields found via Jira fields API. "
            "SLA and customer request type metadata will not be extracted."
        )
    return result


def extract_jsm_metadata(
    issue: Any,
    custom_field_ids: dict[str, str],
) -> dict[str, str | list[str]]:
    """Extract JSM-specific metadata from a Jira issue.

    Args:
        issue: A jira.resources.Issue object.
        custom_field_ids: Mapping of label → customfield_* key, as returned
                          by discover_jsm_custom_field_ids().
    """
    metadata: dict[str, str | list[str]] = {}

    try:
        fields = issue.raw.get("fields", {})

        # JSM custom fields — discovered dynamically to avoid hardcoded IDs
        for label, field_key in custom_field_ids.items():
            field_value = fields.get(field_key)
            if not field_value or not isinstance(field_value, dict):
                continue

            if label == "customer_request_type":
                rt = field_value.get("requestType", {})
                if isinstance(rt, dict) and rt.get("name"):
                    metadata["customer_request_type"] = rt["name"]
            else:
                completed = field_value.get("completedCycles", [])
                ongoing = field_value.get("ongoingCycle", {})
                if completed:
                    metadata[label] = "breached" if completed[-1].get("breached") else "met"
                elif ongoing:
                    metadata[label] = "breached" if ongoing.get("breached") else "ongoing"

        # Status category
        status = fields.get("status", {})
        if isinstance(status, dict):
            status_category = status.get("statusCategory", {})
            if isinstance(status_category, dict) and status_category.get("name"):
                metadata["status_category"] = status_category["name"]

    except (AttributeError, KeyError, TypeError) as e:
        logger.warning(f"Error extracting JSM metadata: {e}")

    return metadata
