"""Utility functions for the Jira Service Management connector."""

from typing import Any

import requests
from jira import JIRA
from requests.auth import HTTPBasicAuth

from onyx.utils.logger import setup_logger

logger = setup_logger()

JSM_API_PATH = "rest/servicedeskapi"


def build_jsm_session(credentials: dict[str, Any], jira_base: str) -> tuple[JIRA, requests.Session, dict[str, Any]]:
    """Build a JIRA client and a requests session configured for JSM API calls.

    Returns:
        Tuple of (jira_client, requests_session, auth_headers)
    """
    api_token = credentials["jira_api_token"]
    session = requests.Session()
    is_cloud = "jira_user_email" in credentials

    if is_cloud:
        email = credentials["jira_user_email"]
        jira_client = JIRA(
            basic_auth=(email, api_token),
            server=jira_base,
            options={"rest_api_version": "3"},
        )
        session.auth = HTTPBasicAuth(email, api_token)
    else:
        jira_client = JIRA(
            token_auth=api_token,
            server=jira_base,
            options={"rest_api_version": "2"},
        )
        session.headers.update({"Authorization": f"Bearer {api_token}"})

    session.headers.update(
        {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-ExperimentalApi": "opt-in",  # Required for some JSM endpoints
        }
    )
    return jira_client, session, {}


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


def get_jsm_project_key(session: requests.Session, jira_base: str, service_desk_id: str) -> str | None:
    """Get the Jira project key for a given service desk ID."""
    url = f"{jira_base.rstrip('/')}/{JSM_API_PATH}/servicedesk/{service_desk_id}"
    try:
        resp = session.get(url)
        resp.raise_for_status()
        return resp.json().get("projectKey")
    except Exception as e:
        logger.warning(f"Failed to get project key for service desk {service_desk_id}: {e}")
        return None


def extract_jsm_metadata(issue: Any) -> dict[str, str | list[str]]:
    """Extract JSM-specific metadata from a Jira issue."""
    metadata: dict[str, str | list[str]] = {}

    try:
        fields = issue.raw.get("fields", {})

        # Request type (JSM-specific)
        request_type = fields.get("issuetype", {})
        if isinstance(request_type, dict):
            metadata["request_type"] = request_type.get("name", "")

        # SLA fields — stored under customfield keys; try common ones
        for field_key, label in [
            ("customfield_10020", "sla_time_to_first_response"),
            ("customfield_10030", "sla_time_to_resolution"),
        ]:
            sla_field = fields.get(field_key)
            if sla_field and isinstance(sla_field, dict):
                completed = sla_field.get("completedCycles", [])
                ongoing = sla_field.get("ongoingCycle", {})
                if completed:
                    last = completed[-1]
                    metadata[label] = (
                        "breached" if last.get("breached") else "met"
                    )
                elif ongoing:
                    metadata[label] = (
                        "breached" if ongoing.get("breached") else "ongoing"
                    )

        # Customer request type
        customer_request = fields.get("customfield_10010")
        if customer_request and isinstance(customer_request, dict):
            rt = customer_request.get("requestType", {})
            if isinstance(rt, dict):
                metadata["customer_request_type"] = rt.get("name", "")

        # Priority
        priority = fields.get("priority", {})
        if isinstance(priority, dict) and priority.get("name"):
            metadata["priority"] = priority["name"]

        # Status category
        status = fields.get("status", {})
        if isinstance(status, dict):
            status_category = status.get("statusCategory", {})
            if isinstance(status_category, dict):
                metadata["status_category"] = status_category.get("name", "")

    except Exception as e:
        logger.warning(f"Error extracting JSM metadata: {e}")

    return metadata
