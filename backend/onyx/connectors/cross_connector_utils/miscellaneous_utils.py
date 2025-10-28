import re
from collections.abc import Callable
from collections.abc import Iterator
from datetime import datetime
from datetime import timezone
from typing import Any
from typing import TypeVar
from urllib.parse import urljoin
from urllib.parse import urlparse

import requests
from dateutil.parser import parse
from dateutil.parser import ParserError

from onyx.configs.app_configs import CONNECTOR_LOCALHOST_OVERRIDE
from onyx.configs.constants import IGNORE_FOR_QA
from onyx.connectors.models import BasicExpertInfo
from onyx.connectors.models import OnyxMetadata
from onyx.utils.text_processing import is_valid_email


T = TypeVar("T")
U = TypeVar("U")


def datetime_to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return dt.astimezone(timezone.utc)


def time_str_to_utc(datetime_str: str) -> datetime:
    # Remove all timezone abbreviations in parentheses
    normalized = re.sub(r"\([A-Z]+\)", "", datetime_str).strip()

    # Remove any remaining parentheses and their contents
    normalized = re.sub(r"\(.*?\)", "", normalized).strip()

    candidates: list[str] = [normalized]

    # Some sources (e.g. Gmail) may prefix the value with labels like "Date:"
    label_stripped = re.sub(
        r"^\s*[A-Za-z][A-Za-z\s_-]*:\s*", "", normalized, count=1
    ).strip()
    if label_stripped and label_stripped != normalized:
        candidates.append(label_stripped)

    # Fix common format issues (e.g. "0000" => "+0000")
    for candidate in list(candidates):
        if " 0000" in candidate:
            fixed = candidate.replace(" 0000", " +0000")
            if fixed not in candidates:
                candidates.append(fixed)

    last_exception: Exception | None = None
    for candidate in candidates:
        try:
            dt = parse(candidate)
            return datetime_to_utc(dt)
        except (ValueError, ParserError) as exc:
            last_exception = exc

    if last_exception is not None:
        raise last_exception

    # Fallback in case parsing failed without raising (should not happen)
    raise ValueError(f"Unable to parse datetime string: {datetime_str}")


def basic_expert_info_representation(info: BasicExpertInfo) -> str | None:
    if info.first_name and info.last_name:
        return f"{info.first_name} {info.middle_initial} {info.last_name}"

    if info.display_name:
        return info.display_name

    if info.email and is_valid_email(info.email):
        return info.email

    if info.first_name:
        return info.first_name

    return None


def get_experts_stores_representations(
    experts: list[BasicExpertInfo] | None,
) -> list[str] | None:
    if not experts:
        return None

    reps = [basic_expert_info_representation(owner) for owner in experts]
    return [owner for owner in reps if owner is not None]


def process_in_batches(
    objects: list[T], process_function: Callable[[T], U], batch_size: int
) -> Iterator[list[U]]:
    for i in range(0, len(objects), batch_size):
        yield [process_function(obj) for obj in objects[i : i + batch_size]]


def get_metadata_keys_to_ignore() -> list[str]:
    return [IGNORE_FOR_QA]


def process_onyx_metadata(
    metadata: dict[str, Any],
) -> tuple[OnyxMetadata, dict[str, Any]]:
    """
    Users may set Onyx metadata and custom tags in text files. https://docs.onyx.app/admin/connectors/official/file
    Any unrecognized fields are treated as custom tags.
    """
    p_owner_names = metadata.get("primary_owners")
    p_owners = (
        [BasicExpertInfo(display_name=name) for name in p_owner_names]
        if p_owner_names
        else None
    )

    s_owner_names = metadata.get("secondary_owners")
    s_owners = (
        [BasicExpertInfo(display_name=name) for name in s_owner_names]
        if s_owner_names
        else None
    )

    dt_str = metadata.get("doc_updated_at")
    doc_updated_at = time_str_to_utc(dt_str) if dt_str else None

    return (
        OnyxMetadata(
            source_type=metadata.get("connector_type"),
            link=metadata.get("link"),
            file_display_name=metadata.get("file_display_name"),
            title=metadata.get("title"),
            primary_owners=p_owners,
            secondary_owners=s_owners,
            doc_updated_at=doc_updated_at,
        ),
        {
            k: v
            for k, v in metadata.items()
            if k
            not in [
                "document_id",
                "time_updated",
                "doc_updated_at",
                "link",
                "primary_owners",
                "secondary_owners",
                "filename",
                "file_display_name",
                "title",
                "connector_type",
                "pdf_password",
                "mime_type",
            ]
        },
    )


def get_oauth_callback_uri(base_domain: str, connector_id: str) -> str:
    if CONNECTOR_LOCALHOST_OVERRIDE:
        # Used for development
        base_domain = CONNECTOR_LOCALHOST_OVERRIDE
    return f"{base_domain.strip('/')}/connector/oauth/callback/{connector_id}"


def is_atlassian_date_error(e: Exception) -> bool:
    return "field 'updated' is invalid" in str(e)


def get_cloudId(base_url: str) -> str:
    tenant_info_url = urljoin(base_url, "/_edge/tenant_info")
    response = requests.get(tenant_info_url, timeout=10)
    response.raise_for_status()
    return response.json()["cloudId"]


def scoped_url(url: str, product: str) -> str:
    parsed = urlparse(url)
    base_url = parsed.scheme + "://" + parsed.netloc
    cloud_id = get_cloudId(base_url)
    return f"https://api.atlassian.com/ex/{product}/{cloud_id}{parsed.path}"
