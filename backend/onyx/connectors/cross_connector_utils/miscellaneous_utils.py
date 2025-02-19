import re
import string
from collections.abc import Callable
from collections.abc import Iterator
from datetime import datetime
from datetime import timezone
from typing import TypeVar

from dateutil.parser import parse
from dateutil.parser import parserinfo

from onyx.configs.app_configs import CONNECTOR_LOCALHOST_OVERRIDE
from onyx.configs.constants import IGNORE_FOR_QA
from onyx.connectors.models import BasicExpertInfo
from onyx.utils.text_processing import is_valid_email


T = TypeVar("T")
U = TypeVar("U")


def _is_valid_tzname(tz_name_str: str) -> bool:
    # based on dateutil.parser _could_be_tzname
    return len(tz_name_str) <= 5 and (
        all(x in string.ascii_uppercase for x in tz_name_str)
        or tz_name_str in parserinfo.UTCZONE
    )


def datetime_to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return dt.astimezone(timezone.utc)


def time_str_to_utc(datetime_str: str) -> datetime:
    try:
        dt = parse(datetime_str)
    except ValueError:
        # Handle malformed timezone by attempting to fix common format issues
        if "0000" in datetime_str:
            # Convert "0000" to "+0000" for proper timezone parsing
            fixed_dt_str = datetime_str.replace(" 0000", " +0000")
            dt = parse(fixed_dt_str)
        elif (
            len(
                matches := list(
                    match
                    for match in re.findall(r"\+\d{4} \(([^)]*)\)", datetime_str)
                    if not _is_valid_tzname(match)
                )
            )
            == 1
        ):
            # Where a string contains both an offset AND a timezone name BUT the name is invalid: remove the name
            # e.g.
            # +0300 (+03) -> +0300
            # +1100 (AUSNSW) -> +1100
            fixed_dt_str = datetime_str.replace(f" ({matches[0]})", "")
            dt = parse(fixed_dt_str)
        else:
            raise
    return datetime_to_utc(dt)


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


def get_oauth_callback_uri(base_domain: str, connector_id: str) -> str:
    if CONNECTOR_LOCALHOST_OVERRIDE:
        # Used for development
        base_domain = CONNECTOR_LOCALHOST_OVERRIDE
    return f"{base_domain.strip('/')}/connector/oauth/callback/{connector_id}"
