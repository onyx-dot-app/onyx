"""Utility helpers for the Jira Service Management connector."""
from typing import Any

import requests
from requests.auth import HTTPBasicAuth

from onyx.utils.logger import setup_logger

logger = setup_logger()

_JSM_API_PATH = "/rest/servicedeskapi"
_JSM_HEADERS = {
    "Accept": "application/json",
    # Required for Service Desk REST API endpoints still in preview
    "X-ExperimentalApi": "opt-in",
}


def get_request_details(
    base_url: str,
    auth: HTTPBasicAuth,
    issue_id_or_key: str,
) -> dict[str, Any]:
    """Return JSM-specific request details (request type, participants, etc.)."""
    url = f"{base_url}{_JSM_API_PATH}/request/{issue_id_or_key}"
    try:
        response = requests.get(url, auth=auth, headers=_JSM_HEADERS, timeout=15)
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        logger.debug(
            f"Could not fetch JSM request details for {issue_id_or_key}: {exc}"
        )
        return {}


def get_sla_information(
    base_url: str,
    auth: HTTPBasicAuth,
    issue_id_or_key: str,
) -> list[dict[str, Any]]:
    """Return a list of SLA records for the given request."""
    url = f"{base_url}{_JSM_API_PATH}/request/{issue_id_or_key}/sla"
    try:
        response = requests.get(url, auth=auth, headers=_JSM_HEADERS, timeout=15)
        response.raise_for_status()
        return response.json().get("values", [])
    except Exception as exc:
        logger.debug(f"Could not fetch SLA info for {issue_id_or_key}: {exc}")
        return []


def format_sla_as_text(sla_list: list[dict[str, Any]]) -> str:
    """Render SLA data as human-readable text suitable for embedding."""
    if not sla_list:
        return ""

    lines = ["SLA Status:"]
    for sla in sla_list:
        name = sla.get("name", "Unknown SLA")
        ongoing = sla.get("ongoingCycle") or {}
        completed = sla.get("completedCycles") or []

        if ongoing:
            breached = ongoing.get("breached", False)
            remaining = (ongoing.get("remainingTime") or {}).get("friendly", "")
            if breached:
                lines.append(f"  {name}: BREACHED")
            else:
                lines.append(f"  {name}: On track ({remaining} remaining)")
        elif completed:
            last = completed[-1]
            breached = last.get("breached", False)
            lines.append(f"  {name}: {'Breached' if breached else 'Met'}")

    return "\n".join(lines)


def get_service_desks(
    base_url: str,
    auth: HTTPBasicAuth,
) -> list[dict[str, Any]]:
    """Return all service desks accessible to the authenticated user."""
    url = f"{base_url}{_JSM_API_PATH}/servicedesk"
    results: list[dict[str, Any]] = []
    start = 0
    limit = 50

    while True:
        response = requests.get(
            url,
            auth=auth,
            headers=_JSM_HEADERS,
            params={"start": start, "limit": limit},
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
        results.extend(data.get("values", []))
        if data.get("isLastPage", True):
            break
        start += limit

    return results
