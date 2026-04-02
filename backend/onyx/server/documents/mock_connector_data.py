"""Utilities for loading mock connector data from a JSON file.

When MOCK_CONNECTOR_FILE_PATH is set, the backend serves connector listing,
detail, and index-attempt endpoints from a static JSON file instead of hitting
the database.  This is useful for frontend development and demos.

Time-offset support
-------------------
Any datetime string field in the JSON can be replaced with an *offset string*
of the form ``"<offset_seconds>"``, e.g. ``"-3600"`` means "1 hour ago" and
``"-86400"`` means "24 hours ago".  Positive values point to the future.
The offset is resolved to an absolute ISO-8601 datetime at load time, so
each request gets a fresh "now".
"""

import json
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any

from onyx.configs.app_configs import MOCK_CONNECTOR_FILE_PATH
from onyx.utils.logger import setup_logger

logger = setup_logger()

# ---- JSON schema top-level keys ------------------------------------------------
_KEY_INDEXING_STATUSES = "indexing_statuses"
_KEY_CC_PAIR_FULL_INFO = "cc_pair_full_info"
_KEY_INDEX_ATTEMPTS = "index_attempts"

# Fields across the relevant Pydantic models that hold datetimes.
_DATETIME_FIELDS: set[str] = {
    # ConnectorIndexingStatusLite
    "last_success",
    # CCPairFullInfo
    "last_indexed",
    "last_pruned",
    "last_full_permission_sync",
    "last_permission_sync_attempt_finished",
    # ConnectorSnapshot / CredentialSnapshot
    "time_created",
    "time_updated",
    "indexing_start",
    # IndexAttemptSnapshot
    "time_started",
    "time_updated",
    "poll_range_start",
    "poll_range_end",
    # IndexAttemptErrorPydantic
    "failed_time_range_start",
    "failed_time_range_end",
    "time_created",
}


def _resolve_time_offsets(obj: Any) -> Any:
    """Walk a JSON-like structure and resolve offset strings to ISO datetimes.

    An offset string is a string that, after stripping whitespace, is parseable
    as an integer or float.  It represents seconds relative to *now*.
    """
    now = datetime.now(tz=timezone.utc)

    if isinstance(obj, dict):
        return {k: _resolve_value(k, v, now) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve_time_offsets(item) for item in obj]
    return obj


def _resolve_value(key: str, value: Any, now: datetime) -> Any:
    if isinstance(value, dict):
        return {k: _resolve_value(k, v, now) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_time_offsets(item) for item in value]
    if key in _DATETIME_FIELDS and isinstance(value, str):
        try:
            offset_seconds = float(value)
            return (now + timedelta(seconds=offset_seconds)).isoformat()
        except ValueError:
            # Not a numeric string – leave it as-is (already an ISO datetime).
            pass
    return value


def _load_raw() -> dict[str, Any] | None:
    """Load and return the raw JSON from MOCK_CONNECTOR_FILE_PATH, or None."""
    if not MOCK_CONNECTOR_FILE_PATH:
        return None
    with open(MOCK_CONNECTOR_FILE_PATH) as f:
        return json.load(f)  # type: ignore[no-any-return]


def load_mock_data() -> dict[str, Any] | None:
    """Load mock data with time offsets resolved. Returns None when mocking is
    disabled."""
    raw = _load_raw()
    if raw is None:
        return None

    # Support both the old format (bare list of indexing statuses) and the new
    # format (dict with explicit keys).
    if isinstance(raw, list):
        raw = {_KEY_INDEXING_STATUSES: raw}

    return _resolve_time_offsets(raw)  # type: ignore[return-value]


def get_mock_indexing_statuses(
    data: dict[str, Any],
) -> list[dict[str, Any]] | None:
    return data.get(_KEY_INDEXING_STATUSES)


def get_mock_cc_pair_full_info(
    data: dict[str, Any],
    cc_pair_id: int,
) -> dict[str, Any] | None:
    by_id = data.get(_KEY_CC_PAIR_FULL_INFO)
    if not by_id:
        return None
    return by_id.get(str(cc_pair_id))


def get_mock_index_attempts(
    data: dict[str, Any],
    cc_pair_id: int,
) -> list[dict[str, Any]] | None:
    by_id = data.get(_KEY_INDEX_ATTEMPTS)
    if not by_id:
        return None
    return by_id.get(str(cc_pair_id))
