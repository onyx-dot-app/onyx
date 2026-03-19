"""Utility helpers for the Jira Service Management connector."""
from typing import Any

import requests
from requests.auth import HTTPBasicAuth

from onyx.utils.logger import setup_logger

logger = setup_logger()

_JSM_API_PATH = "/rest/servicedeskapi"


def get_request_details(
    jsm_base_url: str, auth: HTTPBasicAuth, issue_key: str
) -> dict[str, Any]:
    """Fetch JSM request details for an issue (request type, participants)."""
    url = f"{jsm_base_url}{_JSM_API_PATH}/request/{issue_key}"
    try:
        response = requests.get(url, auth=auth, timeout=15)
        if response.status_code == 404:
            # Not a service desk request - return empty
            return {}
        response.raise_for_status()
        return response.json()
    except Exception:
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
        response = requests.get(url, auth=auth, timeout=15)
        if response.status_code == 404:
            return {}
        response.raise_for_status()
        return response.json()
    except Exception:
        logger.warning(
            f"Failed to fetch SLA information for {issue_key}",
            exc_info=True,
        )
        return {}


def format_sla_as_text(sla_data: dict[str, Any]) -> str:
    """Format SLA data as human-readable text."""
    if not sla_data:
        return ""

    lines = ["SLA Status:"]
    for sla in sla_data.get("values", []):
        goal = sla.get("goal", {})
        name = goal.get("name", "Unknown SLA")
        completed = sla.get("completed", False)
        breached = sla.get("breached", False)
        time_remaining = sla.get("timeRemaining", {})

        if completed:
            status = "Completed"
        elif breached:
            status = "BREACHED"
        else:
            remaining = time_remaining.get("formattedValue", "unknown")
            unit = time_remaining.get("unit", "")
            status = f"{remaining} {unit} remaining"

        lines.append(f"  - {name}: {status}")

    return "\n".join(lines)
