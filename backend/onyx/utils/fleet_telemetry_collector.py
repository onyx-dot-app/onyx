"""Fleet telemetry snapshots of connectors, indexing, and background jobs.

`collect_snapshots` runs every five minutes for each tenant: as a Celery task on
the monitoring worker, or in the API server's poller in Onyx Lite. Each run reads
the rows that changed since the previous run and the work that is still running.
"""

import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, TypeIs

from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CacheBackend
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.fleet_telemetry import (
    attempt_rows,
    connector_rows,
    email_domain_rows,
    job_rows,
    license_row,
    limit_statement_time,
    stage_rows,
)
from onyx.utils.fleet_telemetry import (
    CONNECTOR_ROW_SETTINGS,
    SAFE_BOOLEAN_SETTINGS,
    SAFE_NUMBER_SETTINGS,
    BoundedTelemetry,
    fingerprint,
    get_sender,
)

# The first run reads one hour back. After a long pause, a run reads one day back.
_FIRST_WINDOW: timedelta = timedelta(hours=1)
_MAX_WINDOW: timedelta = timedelta(days=1)
# Each run reads the last minutes of the previous run again, for rows that
# committed late. Their event IDs repeat, so the service drops the copies.
_OVERLAP: timedelta = timedelta(minutes=5)
# Connectors, signup domains, and the license go out when they change, and at
# least every six hours.
_INVENTORY_SECONDS: int = 6 * 3600
_LAST_RUN_KEY: str = "fleet_telemetry_last_run"
_INVENTORY_KEY: str = "fleet_telemetry_inventory"
_RUNNING_STATES: frozenset[str] = frozenset({"not_started", "in_progress"})
# Connector configuration lists that select what to index. Only their sizes leave.
_SELECTION_LISTS: tuple[str, ...] = (
    "folder_ids",
    "folder_paths",
    "channels",
    "channel_names",
    "server_ids",
    "spaces",
    "pages",
    "categories",
    "mailboxes",
    "workspaces",
    "file_locations",
    "spot_names",
    "teams",
    "connector_ids",
)
_ERROR_PATTERNS: tuple[tuple[str, str], ...] = (
    (
        "auth",
        r"\b(?:401|unauthorized|authentication|invalid.?token|expired.?token|credential)\b",
    ),
    ("permission", r"\b(?:403|forbidden|permission.denied|access.denied)\b"),
    ("rate_limit", r"\b(?:429|rate.?limit|too.many.requests|throttl)"),
    ("timeout", r"\b(?:timeout|timed.out|readtimeout|connecttimeout)\b"),
    ("embedding", r"\b(?:embedding|embedder|embeddingerror)\b"),
    (
        "index_write",
        r"\b(?:opensearch|bulkindexerror|vector.database|index.write|write.rejected)\b",
    ),
    ("parse", r"\b(?:parse|parsing|parser|decode|malformed|unsupported.file)\b"),
    (
        "source_unavailable",
        r"\b(?:502|503|504|connection|unreachable|unavailable|connectionerror)\b",
    ),
)
_ERROR_STAGES: dict[str, str] = {
    "embedding": "embed",
    "index_write": "write",
    "parse": "prepare",
}
# A public DNS name. Addresses, single labels, and paths do not match.
_EMAIL_DOMAIN: re.Pattern[str] = re.compile(
    r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?\Z"
)


def _iso(value: object) -> str | None:
    if not isinstance(value, datetime):
        return None
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).isoformat()


def classify_local_error(*samples: object) -> str:
    """Examine bounded local samples; emit only a fixed category, never text."""
    candidate: str = " ".join(
        sample[:2048] for sample in samples if isinstance(sample, str)
    )[:6144]
    for category, pattern in _ERROR_PATTERNS:
        if re.search(pattern, candidate, re.IGNORECASE):
            return category
    return "internal"


def normalize_email_domain(domain: str) -> str | None:
    if not domain or len(domain) > 253:
        return None
    try:
        domain = domain.encode("idna").decode("ascii").lower()
    except UnicodeError:
        return None
    return domain if len(domain) <= 253 and _EMAIL_DOMAIN.fullmatch(domain) else None


def _is_count(value: object) -> TypeIs[int | float]:
    return (
        isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0
    )


def connector_data(row: dict[str, Any]) -> dict[str, Any]:
    """Connector type, state, and counts. Names, paths, and raw settings stay local."""
    config: Any = row.get("config")
    settings: dict[str, Any] = config if isinstance(config, dict) else {}
    metadata: dict[str, bool | int | float] = {
        key: settings[key]
        for key in SAFE_BOOLEAN_SETTINGS
        if isinstance(settings.get(key), bool)
    }
    metadata.update(
        {
            key: settings[key]
            for key in SAFE_NUMBER_SETTINGS
            if _is_count(settings.get(key))
        }
    )
    metadata["selection_count"] = sum(
        len(settings[key])
        for key in _SELECTION_LISTS
        if isinstance(settings.get(key), list)
    )
    metadata["has_time_filter"] = any(
        key in settings for key in ("start_date", "time_range", "start_time")
    )
    for key in CONNECTOR_ROW_SETTINGS:
        value: object = row.get(key)
        if isinstance(value, bool) or _is_count(value):
            metadata[key] = value
    return {
        "connector_id": row["connector_id"],
        "cc_pair_id": row["cc_pair_id"],
        "connector_type": row["source"].value.lower(),
        "state": row["status"].value.lower(),
        "doc_count": row["doc_count"] or 0,
        "last_success_at": _iso(row["last_success_at"]),
        "config_hash": fingerprint(json.dumps(metadata, sort_keys=True)),
        "metadata": metadata,
    }


def attempt_data(row: dict[str, Any]) -> dict[str, Any]:
    connector_type: str = row["source"].value.lower()
    data: dict[str, Any] = {
        "attempt_id": row["attempt_id"],
        "connector_id": row["connector_id"],
        "cc_pair_id": row["cc_pair_id"],
        "connector_type": connector_type,
        "state": row["status"].value.lower(),
        "docs_indexed": row["docs_indexed"],
        "chunks_indexed": row["chunks_indexed"],
        "total_batches": row["total_batches"],
        "completed_batches": row["completed_batches"],
        "error_count": row["error_count"] or 0,
        "counter_mode": "snapshot",
        "started_at": _iso(row["started_at"]),
        "last_progress_at": _iso(row["last_progress_at"]),
        "last_heartbeat_at": _iso(row["last_heartbeat_at"]),
    }
    if row["status"].is_terminal():
        data["ended_at"] = _iso(row["time_updated"])
    if row["error_sample"] is not None or row["error_count"]:
        category: str = classify_local_error(
            row["item_error_type"], row["error_sample"], row["item_error_sample"]
        )
        data["error_count"] = max(
            data["error_count"], int(row["error_sample"] is not None)
        )
        data["error_code"] = category
        data["error_fingerprint"] = fingerprint(f"attempt:{connector_type}:{category}")
        if category in _ERROR_STAGES:
            data["stage"] = _ERROR_STAGES[category]
    return data


def job_data(row: dict[str, Any]) -> dict[str, Any]:
    data: dict[str, Any] = {
        key: row[key]
        for key in (
            "job_id",
            "job_type",
            "state",
            "entity_id",
            "docs_processed",
            "users_processed",
            "groups_processed",
            "memberships_synced",
        )
    }
    if row["cc_pair_id"] is not None:
        data["cc_pair_id"] = row["cc_pair_id"]
    data["started_at"] = _iso(row["started_at"])
    data["ended_at"] = _iso(row["ended_at"])
    data["error_count"] = max(row["error_count"], int(row["state"] == "failed"))
    if row["started_at"] and row["ended_at"]:
        data["duration_ms"] = max(
            0, (row["ended_at"] - row["started_at"]).total_seconds() * 1000
        )
    return data


def _send(
    sender: BoundedTelemetry,
    tenant_id: str,
    event_type: str,
    data: dict[str, Any],
    entity: str,
    revision: datetime,
    occurred_at: datetime | None = None,
) -> None:
    """Send with an event ID made from the row's identity and revision time."""
    identity: str = f"{tenant_id}:{entity}:{revision.isoformat()}"
    if occurred_at is not None:
        # Running work changes its counters without a new revision time.
        identity += ":" + fingerprint(json.dumps(data, sort_keys=True))
    sender.emit(
        event_type,
        data,
        tenant_id=tenant_id,
        event_id=str(uuid.uuid5(uuid.UUID(str(sender.customer_uuid)), identity)),
        occurred_at=(occurred_at or revision).timestamp(),
    )


def _send_inventory(
    sender: BoundedTelemetry,
    cache: CacheBackend,
    tenant_id: str,
    inventory: list[tuple[str, dict[str, Any]]],
) -> None:
    """Send the inventory when it changed, or when the last copy expired."""
    signature: str = fingerprint(json.dumps(inventory, sort_keys=True))
    previous: bytes | None = cache.get(_INVENTORY_KEY)
    if previous is not None and previous.decode() == signature:
        return
    sent: list[bool] = [
        sender.emit(event_type, data, tenant_id=tenant_id)
        for event_type, data in inventory
    ]
    if all(sent):
        cache.set(_INVENTORY_KEY, signature, ex=_INVENTORY_SECONDS)


def collect_snapshots(tenant_id: str) -> None:
    """One collection pass for one tenant. Never raises."""
    sender: BoundedTelemetry | None = get_sender()
    # Event IDs live in the namespace that enrollment assigns.
    if sender is None or sender.customer_uuid is None:
        return
    started: datetime = datetime.now(timezone.utc)
    try:
        cache: CacheBackend = get_cache_backend(tenant_id=tenant_id)
        last_run: bytes | None = cache.get(_LAST_RUN_KEY)
        since: datetime = started - _FIRST_WINDOW
        if last_run is not None:
            since = max(
                datetime.fromisoformat(last_run.decode()) - _OVERLAP,
                started - _MAX_WINDOW,
            )
        with get_session_with_tenant(tenant_id=tenant_id) as db_session:
            limit_statement_time(db_session)
            inventory: list[tuple[str, dict[str, Any]]] = [
                ("connector", connector_data(row)) for row in connector_rows(db_session)
            ]
            for row in email_domain_rows(db_session):
                domain: str | None = normalize_email_domain(row["domain"] or "")
                if domain and row["first_signup_at"] is not None:
                    inventory.append(
                        (
                            "tenant_domain",
                            {
                                "domain": domain,
                                "first_signup_at": _iso(row["first_signup_at"]),
                            },
                        )
                    )
            license: dict[str, Any] = license_row(db_session)
            inventory.append(
                (
                    "license",
                    {
                        "license_present": bool(license["license_present"]),
                        "first_set_at": _iso(license["first_set_at"]),
                    },
                )
            )
            attempts: list[dict[str, Any]] = attempt_rows(db_session, since)
            stages: list[dict[str, Any]] = stage_rows(
                db_session, [row["attempt_id"] for row in attempts], since
            )
            jobs: list[dict[str, Any]] = job_rows(db_session, since)
        _send_inventory(sender, cache, tenant_id, inventory)
        for row in attempts:
            _send(
                sender,
                tenant_id,
                "attempt",
                attempt_data(row),
                f"attempt:{row['attempt_id']}",
                row["time_updated"],
            )
        by_attempt: dict[int, dict[str, Any]] = {
            row["attempt_id"]: row for row in attempts
        }
        for row in stages:
            attempt: dict[str, Any] = by_attempt[row["attempt_id"]]
            stage_data: dict[str, Any] = {
                key: row[key]
                for key in (
                    "attempt_id",
                    "event_count",
                    "total_duration_ms",
                    "min_duration_ms",
                    "max_duration_ms",
                    "m2_duration_ms",
                )
            }
            stage_data.update(
                connector_id=attempt["connector_id"],
                cc_pair_id=attempt["cc_pair_id"],
                connector_type=attempt["source"].value.lower(),
                stage_name=row["stage"].value,
                first_event_at=_iso(row["first_event_at"]),
                last_event_at=_iso(row["last_event_at"]),
            )
            # The service requires the event time to equal the summary's last update.
            _send(
                sender,
                tenant_id,
                "stage",
                stage_data,
                f"stage:{row['attempt_id']}:{row['stage'].value}",
                row["last_event_at"],
            )
        for row in jobs:
            if row["revision_at"] is not None:
                _send(
                    sender,
                    tenant_id,
                    "job",
                    job_data(row),
                    row["job_id"],
                    row["revision_at"],
                    started if row["state"] in _RUNNING_STATES else None,
                )
        cache.set(_LAST_RUN_KEY, started.isoformat(), ex=7 * 24 * 3600)
        sender.health["source_consecutive_errors"] = 0
        sender.health["last_source_success_at"] = started.isoformat()
    except Exception:
        # No SQL, identifiers, or exception text leave the process.
        sender.health["source_errors"] = sender.health.get("source_errors", 0) + 1
        sender.health["source_consecutive_errors"] = (
            sender.health.get("source_consecutive_errors", 0) + 1
        )
