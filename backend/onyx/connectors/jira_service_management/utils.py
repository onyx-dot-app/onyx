"""Utility helpers for the Jira Service Management connector."""
from typing import Any

import requests
from requests.auth import HTTPBasicAuth

from onyx.utils.logger import setup_logger

logger = setup_logger()

_JSM_API_PATH = "/rest/servicedeskapi"

# Headers for JSM API requests
_JSM_HEADERS = {"Accept": "application/json"}


def get_request_details(
    jsm_base_url: str, auth: HTTPBasicAuth, issue_key: str
) -> dict[str, Any]:
    """Fetch JSM request details for an issue (request type, participants)."""
    url = f"{jsm_base_url}{_JSM_API_PATH}/request/{issue_key}"
    try:
        response = requests.get(url, auth=auth, headers=_JSM_HEADERS, timeout=15)
        if response.status_code == 404:
            # Not a service desk request - return empty
            return {}
        if response.status_code == 429:
            logger.warning(f"Rate limited fetching request details for {issue_key}")
            return {}
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException:
        logger.warning(
            f"Failed to fetch request details for {issue_key}",
            exc_info=True,
        )
        return {}


def get_sla_information(
    jsm_base_url: str, auth: HTTPBasicAuth, issue_key: str
) -> dict[str, Any]:
    """Fetch SLA information for a JSM request."""
    url = f"{jsm_base_url}{_JSM_API_PATH}/request/{issue_key}/sla"
    try:
        response = requests.get(url, auth=auth, headers=_JSM_HEADERS, timeout=15)
        if response.status_code == 404:
            return {}
        if response.status_code == 429:
            logger.warning(f"Rate limited fetching SLA for {issue_key}")
            return {}
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException:
        logger.warning(
            f"Failed to fetch SLA information for {issue_key}",
            exc_info=True,
        )
        return {}


def format_sla_as_text(sla_data: dict[str, Any]) -> str:
    """Format SLA data as human-readable text."""
    if not sla_data:
        return ""

    # Check if there are actual SLA values
    values = sla_data.get("values", [])
    if not values:
        return ""

    lines = ["SLA Status:"]
    for sla in values:
        # SLA name is at top level, not in goal object
        name = sla.get("name", "Unknown SLA")
        completed_cycles = sla.get("completedCycles", [])
        breached = any(c.get("breached", False) for c in completed_cycles)
        ongoing = sla.get("ongoingCycle") or {}
        time_remaining = ongoing.get("remainingTime") or {}

        if ongoing.get("completed", False):
            status = "Completed"
        elif breached:
            status = "BREACHED"
        else:
            remaining = time_remaining.get("friendly", "")
            status = f"{remaining} remaining" if remaining else "In progress"

        lines.append(f"  - {name}: {status}")

    return "\n".join(lines)
