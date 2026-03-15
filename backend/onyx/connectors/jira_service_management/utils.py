from __future__ import annotations

import html
import re
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import requests
from jira import JIRA

from onyx.connectors.jira.utils import extract_text_from_adf
from onyx.utils.logger import setup_logger

logger = setup_logger()

JSM_API_PAGE_SIZE = 50
JSM_QUEUE_ISSUE_SCAN_LIMIT = 5000
JSM_REQUEST_EXPAND = "participant,status,requestType,serviceDesk"
JSM_MAX_PAGINATION_PAGES = 10000


@dataclass(frozen=True)
class JSMServiceDesk:
    service_desk_id: str
    project_key: str | None
    project_name: str | None
    project_id: str | None
    portal_id: str | None


@dataclass(frozen=True)
class JSMRequestType:
    request_type_id: str
    name: str | None
    description: str | None
    help_text: str | None
    issue_type_id: str | None
    group_ids: tuple[str, ...]


@dataclass(frozen=True)
class JSMQueue:
    queue_id: str
    name: str | None
    jql: str | None
    issue_count: int | None


def _build_servicedesk_api_url(jira_client: JIRA, path: str) -> str:
    server_url = str(jira_client._options["server"]).rstrip("/")
    normalized_path = path.lstrip("/")
    return f"{server_url}/rest/servicedeskapi/{normalized_path}"


def _raise_for_http_status(response: requests.Response, path: str) -> None:
    try:
        response.raise_for_status()
    except requests.HTTPError:
        logger.debug(
            "JSM API request failed. path=%s status=%s body=%s",
            path,
            response.status_code,
            response.text,
        )
        raise


def jsm_get_json(
    jira_client: JIRA,
    path: str,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    response = jira_client._session.get(
        _build_servicedesk_api_url(jira_client, path),
        params=params,
        headers=headers,
    )
    _raise_for_http_status(response, path)
    response_json = response.json()
    if not isinstance(response_json, dict):
        raise RuntimeError(f"Unexpected JSM payload for path '{path}': {response_json}")
    return response_json


def jsm_get_json_optional(
    jira_client: JIRA,
    path: str,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    allowed_status_codes: tuple[int, ...] = (403, 404),
) -> dict[str, Any] | None:
    try:
        return jsm_get_json(
            jira_client=jira_client,
            path=path,
            params=params,
            headers=headers,
        )
    except requests.HTTPError as exc:
        response = exc.response
        status_code = response.status_code if response is not None else None
        if status_code in allowed_status_codes:
            return None
        raise


def iter_jsm_paginated_values(
    jira_client: JIRA,
    path: str,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    page_size: int = JSM_API_PAGE_SIZE,
) -> Iterator[dict[str, Any]]:
    start = 0

    for _page_number in range(JSM_MAX_PAGINATION_PAGES):
        page_params = dict(params or {})
        page_params["start"] = start
        page_params["limit"] = page_size

        page = jsm_get_json(
            jira_client=jira_client,
            path=path,
            params=page_params,
            headers=headers,
        )
        raw_values = page.get("values", [])
        if not isinstance(raw_values, list):
            raise RuntimeError(f"Unexpected paginated JSM response for path '{path}'")

        values = [value for value in raw_values if isinstance(value, dict)]
        for value in values:
            yield value

        if not values:
            break

        if page.get("isLastPage") is True:
            break

        size = page.get("size")
        if isinstance(size, int) and size > 0:
            start += size
        else:
            start += len(values)
    else:
        logger.warning(
            "Stopping JSM pagination for path %s after reaching page limit %s",
            path,
            JSM_MAX_PAGINATION_PAGES,
        )


def iter_jsm_paginated_values_optional(
    jira_client: JIRA,
    path: str,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    page_size: int = JSM_API_PAGE_SIZE,
    allowed_status_codes: tuple[int, ...] = (403, 404),
) -> Iterator[dict[str, Any]]:
    start = 0

    for _page_number in range(JSM_MAX_PAGINATION_PAGES):
        page_params = dict(params or {})
        page_params["start"] = start
        page_params["limit"] = page_size

        page = jsm_get_json_optional(
            jira_client=jira_client,
            path=path,
            params=page_params,
            headers=headers,
            allowed_status_codes=allowed_status_codes,
        )
        if page is None:
            break

        raw_values = page.get("values", [])
        if not isinstance(raw_values, list):
            raise RuntimeError(f"Unexpected paginated JSM response for path '{path}'")

        values = [value for value in raw_values if isinstance(value, dict)]
        for value in values:
            yield value

        if not values:
            break

        if page.get("isLastPage") is True:
            break

        size = page.get("size")
        if isinstance(size, int) and size > 0:
            start += size
        else:
            start += len(values)
    else:
        logger.warning(
            "Stopping optional JSM pagination for path %s after reaching page limit %s",
            path,
            JSM_MAX_PAGINATION_PAGES,
        )


def list_service_desks(jira_client: JIRA) -> list[JSMServiceDesk]:
    service_desks: list[JSMServiceDesk] = []

    for raw_service_desk in iter_jsm_paginated_values(
        jira_client=jira_client,
        path="servicedesk",
    ):
        service_desks.append(
            JSMServiceDesk(
                service_desk_id=str(
                    raw_service_desk.get("id")
                    or raw_service_desk.get("serviceDeskId")
                    or ""
                ),
                project_key=_coerce_optional_str(raw_service_desk.get("projectKey")),
                project_name=_coerce_optional_str(raw_service_desk.get("projectName")),
                project_id=_coerce_optional_str(raw_service_desk.get("projectId")),
                portal_id=_coerce_optional_str(raw_service_desk.get("portalId")),
            )
        )

    return [service_desk for service_desk in service_desks if service_desk.service_desk_id]


def list_request_types(
    jira_client: JIRA,
    service_desk_id: str,
) -> list[JSMRequestType]:
    request_types: list[JSMRequestType] = []
    path = f"servicedesk/{service_desk_id}/requesttype"

    for raw_request_type in iter_jsm_paginated_values(
        jira_client=jira_client,
        path=path,
    ):
        raw_group_ids = raw_request_type.get("groupIds", [])
        group_ids = tuple(
            str(group_id)
            for group_id in raw_group_ids
            if group_id is not None and str(group_id).strip()
        )
        request_type_id = _coerce_optional_str(raw_request_type.get("id"))
        if not request_type_id:
            continue

        request_types.append(
            JSMRequestType(
                request_type_id=request_type_id,
                name=_coerce_optional_str(raw_request_type.get("name")),
                description=_coerce_optional_str(raw_request_type.get("description")),
                help_text=_coerce_optional_str(raw_request_type.get("helpText")),
                issue_type_id=_coerce_optional_str(raw_request_type.get("issueTypeId")),
                group_ids=group_ids,
            )
        )

    return request_types


def get_customer_request(
    jira_client: JIRA,
    issue_id_or_key: str,
    expand: str = JSM_REQUEST_EXPAND,
) -> dict[str, Any] | None:
    return jsm_get_json_optional(
        jira_client=jira_client,
        path=f"request/{issue_id_or_key}",
        params={"expand": expand},
        allowed_status_codes=(403, 404),
    )


def list_request_participants(
    jira_client: JIRA,
    issue_id_or_key: str,
) -> list[dict[str, Any]]:
    return list(
        iter_jsm_paginated_values_optional(
            jira_client=jira_client,
            path=f"request/{issue_id_or_key}/participant",
            allowed_status_codes=(403, 404),
        )
    )


def list_request_slas(
    jira_client: JIRA,
    issue_id_or_key: str,
) -> list[dict[str, Any]]:
    return list(
        iter_jsm_paginated_values_optional(
            jira_client=jira_client,
            path=f"request/{issue_id_or_key}/sla",
            allowed_status_codes=(403, 404),
        )
    )


def list_request_approvals(
    jira_client: JIRA,
    issue_id_or_key: str,
) -> list[dict[str, Any]]:
    return list(
        iter_jsm_paginated_values_optional(
            jira_client=jira_client,
            path=f"request/{issue_id_or_key}/approval",
            allowed_status_codes=(403, 404),
        )
    )


def get_approval(
    jira_client: JIRA,
    issue_id_or_key: str,
    approval_id: str,
) -> dict[str, Any] | None:
    return jsm_get_json_optional(
        jira_client=jira_client,
        path=f"request/{issue_id_or_key}/approval/{approval_id}",
        allowed_status_codes=(403, 404),
    )


def list_queues(
    jira_client: JIRA,
    service_desk_id: str,
) -> list[JSMQueue]:
    queues: list[JSMQueue] = []
    path = f"servicedesk/{service_desk_id}/queue"

    for raw_queue in iter_jsm_paginated_values(
        jira_client=jira_client,
        path=path,
        params={"includeCount": "true"},
    ):
        queue_id = _coerce_optional_str(raw_queue.get("id"))
        if not queue_id:
            continue

        issue_count: int | None = None
        raw_issue_count = raw_queue.get("issueCount")
        if isinstance(raw_issue_count, int):
            issue_count = raw_issue_count
        elif isinstance(raw_issue_count, str) and raw_issue_count.isdigit():
            issue_count = int(raw_issue_count)

        queues.append(
            JSMQueue(
                queue_id=queue_id,
                name=_coerce_optional_str(raw_queue.get("name")),
                jql=_coerce_optional_str(raw_queue.get("jql")),
                issue_count=issue_count,
            )
        )

    return queues


def build_queue_membership_map(
    jira_client: JIRA,
    service_desk_id: str,
    queue_scan_limit: int = JSM_QUEUE_ISSUE_SCAN_LIMIT,
) -> dict[str, list[JSMQueue]]:
    queues = list_queues(jira_client=jira_client, service_desk_id=service_desk_id)
    membership: defaultdict[str, list[JSMQueue]] = defaultdict(list)
    limit_reached = False
    for queue in queues:
        path = f"servicedesk/{service_desk_id}/queue/{queue.queue_id}/issue"
        # Keep scanning later queues after hitting the unique-issue cap so already-seen
        # issues can still accumulate their full queue memberships across the service desk.
        for raw_issue in iter_jsm_paginated_values(
            jira_client=jira_client,
            path=path,
        ):
            issue_key = extract_queue_issue_key(raw_issue)
            if not issue_key:
                continue
            if issue_key not in membership and len(membership) >= queue_scan_limit:
                if not limit_reached:
                    logger.info(
                        "Reached JSM queue membership limit for service desk %s after %s unique issues; skipping new issues beyond limit %s",
                        service_desk_id,
                        len(membership),
                        queue_scan_limit,
                    )
                    limit_reached = True
                continue
            membership[issue_key].append(queue)

    return dict(membership)


def extract_queue_issue_key(raw_issue: dict[str, Any]) -> str | None:
    possible_keys = (
        raw_issue.get("issueKey"),
        raw_issue.get("key"),
        raw_issue.get("idOrKey"),
    )
    for possible_key in possible_keys:
        normalized = _coerce_optional_str(possible_key)
        if normalized:
            return normalized

    issue = raw_issue.get("issue")
    if isinstance(issue, dict):
        return extract_queue_issue_key(issue)

    return None


def jsm_user_to_basic_expert_info(user: dict[str, Any] | None) -> dict[str, str] | None:
    if not user:
        return None

    display_name = _coerce_optional_str(
        user.get("displayName")
        or user.get("name")
        or user.get("fullName")
        or user.get("accountId")
    )
    email = _coerce_optional_str(user.get("emailAddress") or user.get("email"))
    account_id = _coerce_optional_str(user.get("accountId"))

    if not display_name and not email and not account_id:
        return None

    user_info: dict[str, str] = {}
    if display_name:
        user_info["display_name"] = display_name
    if email:
        user_info["email"] = email
    if account_id:
        user_info["account_id"] = account_id
    return user_info


def format_request_field_values(
    request_field_values: list[dict[str, Any]],
) -> list[str]:
    formatted_fields: list[str] = []

    for field_value in request_field_values:
        label = _coerce_optional_str(
            field_value.get("label")
            or field_value.get("fieldName")
            or field_value.get("fieldId")
        )
        if not label:
            continue

        rendered_value = field_value.get("renderedValue")
        value = rendered_value if rendered_value is not None else field_value.get("value")
        text_value = stringify_jsm_value(value)
        if text_value:
            formatted_fields.append(f"{label}: {text_value}")

    return formatted_fields


def format_sla_summaries(slas: list[dict[str, Any]]) -> list[str]:
    summaries: list[str] = []

    for sla in slas:
        name = _coerce_optional_str(sla.get("name") or sla.get("metricName"))
        if not name:
            continue

        details: list[str] = []
        ongoing_cycle = sla.get("ongoingCycle")
        if isinstance(ongoing_cycle, dict):
            if _extract_friendly_time(ongoing_cycle.get("elapsedTime")):
                details.append(
                    f"elapsed {_extract_friendly_time(ongoing_cycle.get('elapsedTime'))}"
                )
            if _extract_friendly_time(ongoing_cycle.get("remainingTime")):
                details.append(
                    f"remaining {_extract_friendly_time(ongoing_cycle.get('remainingTime'))}"
                )
            if ongoing_cycle.get("breached") is True:
                details.append("breached")
        else:
            completed_cycles = sla.get("completedCycles")
            if isinstance(completed_cycles, list) and completed_cycles:
                latest_cycle = completed_cycles[-1]
                if isinstance(latest_cycle, dict):
                    if _extract_friendly_time(latest_cycle.get("elapsedTime")):
                        details.append(
                            f"completed in {_extract_friendly_time(latest_cycle.get('elapsedTime'))}"
                        )
                    if latest_cycle.get("breached") is True:
                        details.append("breached")

        summaries.append(f"{name}: {', '.join(details) if details else 'tracked'}")

    return summaries


def format_approval_summaries(approvals: list[dict[str, Any]]) -> list[str]:
    summaries: list[str] = []

    for approval in approvals:
        name = _coerce_optional_str(approval.get("name")) or "Approval"
        approvers = approval.get("approvers")
        approver_names: list[str] = []
        if isinstance(approvers, list):
            for approver in approvers:
                if isinstance(approver, dict):
                    user = approver.get("approver")
                    if isinstance(user, dict):
                        user_info = jsm_user_to_basic_expert_info(user)
                        if user_info and user_info.get("display_name"):
                            approver_names.append(user_info["display_name"])

        decision = _coerce_optional_str(
            approval.get("finalDecision")
            or approval.get("status")
        )
        decision_text = decision or "pending"
        if approver_names:
            summaries.append(f"{name}: {decision_text} ({', '.join(approver_names)})")
        else:
            summaries.append(f"{name}: {decision_text}")

    return summaries


def format_queue_summaries(queues: list[JSMQueue]) -> list[str]:
    summaries: list[str] = []
    for queue in queues:
        queue_name = queue.name or queue.queue_id
        if queue.issue_count is not None:
            summaries.append(f"{queue_name} ({queue.issue_count})")
        else:
            summaries.append(queue_name)
    return summaries


def stringify_jsm_value(value: Any) -> str:
    if value is None:
        return ""

    if isinstance(value, str):
        return value.strip()

    if isinstance(value, bool):
        return "true" if value else "false"

    if isinstance(value, (int, float)):
        return str(value)

    if isinstance(value, list):
        parts = [stringify_jsm_value(item) for item in value]
        return ", ".join([part for part in parts if part])

    if isinstance(value, dict):
        if "friendly" in value and isinstance(value["friendly"], str):
            return value["friendly"].strip()

        if "displayName" in value and isinstance(value["displayName"], str):
            return value["displayName"].strip()

        if "name" in value and isinstance(value["name"], str):
            return value["name"].strip()

        if "emailAddress" in value and isinstance(value["emailAddress"], str):
            return value["emailAddress"].strip()

        if "text" in value and isinstance(value["text"], str):
            return value["text"].strip()

        if "html" in value and isinstance(value["html"], str):
            return _strip_html(value["html"])

        if "value" in value:
            return stringify_jsm_value(value["value"])

        if "content" in value:
            try:
                adf_text = extract_text_from_adf(value)
                if adf_text:
                    return adf_text
            except Exception:
                pass

        parts = []
        for nested_key in ("label", "status", "statusCategory", "currentStatus"):
            if nested_key in value:
                nested_value = stringify_jsm_value(value[nested_key])
                if nested_value:
                    parts.append(nested_value)
        return ", ".join(parts)

    return str(value).strip()


def append_with_byte_limit(
    existing_text: str,
    text_to_append: str,
    max_bytes: int,
) -> str:
    existing_text_bytes = existing_text.encode("utf-8")
    if len(existing_text_bytes) >= max_bytes:
        return existing_text

    if not text_to_append:
        return existing_text

    combined_text = existing_text.rstrip()
    separator = "\n\n" if combined_text else ""
    appended = f"{combined_text}{separator}{text_to_append.strip()}"
    if len(appended.encode("utf-8")) <= max_bytes:
        return appended

    remaining_bytes = max_bytes - len((combined_text + separator).encode("utf-8"))
    if remaining_bytes <= 0:
        return combined_text

    truncated = _truncate_to_byte_limit(text_to_append.strip(), remaining_bytes)
    return f"{combined_text}{separator}{truncated}".strip()


def absolute_jsm_link(base_url: str, maybe_relative_url: str | None) -> str | None:
    if not maybe_relative_url:
        return None

    if maybe_relative_url.startswith("http://") or maybe_relative_url.startswith(
        "https://"
    ):
        return maybe_relative_url

    return urljoin(base_url.rstrip("/") + "/", maybe_relative_url.lstrip("/"))


def coerce_optional_str(value: Any) -> str | None:
    if value is None:
        return None

    coerced = str(value).strip()
    return coerced or None


_coerce_optional_str = coerce_optional_str


def _extract_friendly_time(value: Any) -> str | None:
    if isinstance(value, dict):
        friendly = value.get("friendly")
        if isinstance(friendly, str) and friendly.strip():
            return friendly.strip()
    return None


def _strip_html(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(without_tags)).strip()


def _truncate_to_byte_limit(value: str, max_bytes: int) -> str:
    if max_bytes <= 0:
        return ""

    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value

    if max_bytes < 4:
        return encoded[:max_bytes].decode("utf-8", errors="ignore").rstrip()

    truncated = encoded[: max(0, max_bytes - 3)].decode("utf-8", errors="ignore")
    return truncated.rstrip() + "..."
