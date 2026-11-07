from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from onyx.connectors.models import BasicExpertInfo

JSM_ID_PREFIX = "JSM_"


@dataclass(frozen=True)
class JsmRequestEndpoint:
    base_url: str
    auth: tuple[str, str]


@dataclass(frozen=True)
class JsmPollWindow:
    start: datetime | None = None
    end: datetime | None = None


@dataclass(frozen=True)
class JsmTicketRenderContext:
    base_url: str
    default_project_key: str | None
    comments: list[dict[str, Any]]


def parse_iso_string(iso_str: str) -> datetime | None:
    # Converts an ISO-8601 timestamp string into a timezone-aware UTC datetime.
    normalized = iso_str.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        return parsed.astimezone(timezone.utc)
    return parsed.replace(tzinfo=timezone.utc)


def parse_jsm_timestamp(raw_value: Any) -> datetime | None:
    # Parses Jira Service Management DateDTO objects or ISO strings into UTC datetimes.
    if isinstance(raw_value, str):
        return parse_iso_string(raw_value)
    if not isinstance(raw_value, dict):
        return None
    epoch_ms = raw_value.get("epochMillis")
    if isinstance(epoch_ms, int | float):
        return datetime.fromtimestamp(epoch_ms / 1000.0, tz=timezone.utc)
    iso_val = raw_value.get("iso8601")
    return parse_iso_string(iso_val) if isinstance(iso_val, str) else None


def extract_expert_info(user_dict: Any) -> BasicExpertInfo | None:
    # Extracts reporter or assignee identity from a Jira user object.
    if not isinstance(user_dict, dict):
        return None
    display_name = user_dict.get("displayName") or user_dict.get("name")
    email = user_dict.get("emailAddress")
    if not display_name and not email:
        return None
    return BasicExpertInfo(display_name=display_name, email=email)
