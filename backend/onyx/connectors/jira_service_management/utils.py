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

    values = sla_data.get("values", [])
    if not values:
        return ""

    lines: list[str] = []
    for sla in values:
        name = sla.get("name", "Unknown SLA")
        ongoing: dict[str, Any] = sla.get("ongoingCycle") or {}
        completed_cycles: list[Any] = sla.get("completedCycles") or []

        breached: bool = ongoing.get("breached", False) or any(
            c.get("breached", False) for c in completed_cycles
        )
        completed: bool = bool(completed_cycles) and not ongoing

        time_remaining: dict[str, Any] = ongoing.get("remainingTime") or {}

        if breached:
            status = "BREACHED"
        elif completed:
            status = "Completed"
        else:
            remaining = time_remaining.get("friendly", "unknown")
            status = f"{remaining} remaining"

        lines.append(f"  - {name}: {status}")

    return "\n".join(lines) if lines else ""
