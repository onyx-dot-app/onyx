"""Fleet telemetry snapshots of connectors, indexing, and background jobs.

`collect_snapshots` runs every five minutes for each tenant: as a Celery task on
the monitoring worker, or in the API server's poller in Onyx Lite. Each run reads
the rows that changed since the previous run and the work that is still running.
"""

import json
import random
import re
import uuid
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from itertools import groupby
from typing import Any, TypedDict, TypeIs

from sqlalchemy.orm import Session

from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CacheBackend
from onyx.configs.app_configs import DISABLE_VECTOR_DB, OAUTH_ENABLED
from onyx.configs.constants import DocumentSource
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.fleet_telemetry import (
    ERROR_SAMPLE_CHARS,
    ROW_LIMIT,
    attempt_rows,
    connector_rows,
    email_domain_rows,
    first_question_at,
    has_indexed_connectors__no_commit,
    job_rows,
    license_row,
    limit_statement_time,
    setup_counts,
    stage_rows,
    standard_user_counts,
    usage_counts,
    usage_week_rows,
)
from onyx.llm.constants import LlmProviderNames
from onyx.server.runtime.onyx_runtime import OnyxRuntime
from onyx.utils.fleet_telemetry import (
    CONNECTOR_ROW_SETTINGS,
    DEPLOYMENT_TYPE,
    SAFE_BOOLEAN_SETTINGS,
    SAFE_NUMBER_SETTINGS,
    BoundedTelemetry,
    fingerprint,
    get_sender,
    sanitize_data,
)
from onyx.utils.variable_functionality import fetch_ee_implementation_or_noop
from shared_configs.configs import MULTI_TENANT

# The first run reads one hour back. After a long pause, a run reads one day back.
_FIRST_WINDOW: timedelta = timedelta(hours=1)
_MAX_WINDOW: timedelta = timedelta(days=1)
# Each run reads the last minutes of the previous run again, for rows that
# committed late. Their event IDs repeat, so the service drops the copies.
_OVERLAP: timedelta = timedelta(minutes=5)
# Each connector, signup domain, the license, and the user count goes out when it
# changes, and again six hours after its own last send. The fleet service relies
# on that bound to tell a deleted connector from a quiet one.
_INVENTORY_SECONDS: int = 6 * 3600
# Where the next run starts reading.
_CURSOR_KEY: str = "fleet_telemetry_cursor"
# Each inventory item's fingerprint and last send time.
_INVENTORY_ITEMS_KEY: str = "fleet_telemetry_inventory_items"
_CACHE_SECONDS: int = 7 * 24 * 3600
# Finished attempts and jobs that ended longer ago are not sent. The service rejects
# attempt and job events more than 190 days old, also when it processes them days
# after receipt, and it deletes their states after six months. Do not raise this
# toward either.
_FINISHED_HORIZON: timedelta = timedelta(days=180)
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
# Usage and setup counts go out about once an hour. Cloud runs a pass for each
# tenant, so each tenant's first read waits a random part of the hour, and each
# later read a random part of the jitter, to spread them out.
_USAGE_SECONDS: float = 3600
_USAGE_JITTER_SECONDS: float = 600
_USAGE_DUE_KEY: str = "fleet_telemetry_usage_due"
# The weekly history goes out a few weeks per read, with a random gap between
# reads, from the first question to the last completed week. About every 30 days
# it starts again from the first week, so a lost or changed week is corrected.
# The service replaces each week, so sending a week again never adds to it.
_HISTORY_KEY: str = "fleet_telemetry_usage_history"
_HISTORY_WEEKS_PER_READ: int = 4
_HISTORY_GAP_SECONDS: tuple[float, float] = (600, 1800)
_HISTORY_REFRESH: timedelta = timedelta(days=30)
# Onyx chat history cannot start earlier. Bounds the weeks a wrong clock can add.
_EARLIEST_WEEK: date = date(2023, 1, 2)
_LLM_PROVIDER_TYPES: frozenset[str] = frozenset(name.value for name in LlmProviderNames)
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
        sample[:ERROR_SAMPLE_CHARS] for sample in samples if isinstance(sample, str)
    )[: 3 * ERROR_SAMPLE_CHARS]
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


# Seconds between a pair's doc permission syncs and between its group syncs.
SyncCadences = tuple[int | None, int | None]


def permission_sync_cadence_reader() -> Callable[[dict[str, Any]], SyncCadences]:
    """Returns a reader of how often a pair's permission syncs run now, by the
    schedulers' own rules. A sync that cannot run now has no cadence. Dispatch
    also waits while the pair is pruned; the fleet service allows for that. Onyx
    Lite runs neither sync, and a build without Enterprise code has none."""
    if DISABLE_VECTOR_DB:
        return lambda _row: (None, None)
    doc_seconds: Callable[
        [DocumentSource, ConnectorCredentialPairStatus, bool], int | None
    ] = fetch_ee_implementation_or_noop(
        "onyx.external_permissions.sync_params", "doc_permission_sync_seconds"
    )
    group_seconds: Callable[
        [DocumentSource, ConnectorCredentialPairStatus], int | None
    ] = fetch_ee_implementation_or_noop(
        "onyx.external_permissions.sync_params", "external_group_sync_seconds"
    )

    # The doc sync scheduler stretches its period by this runtime setting. Read
    # once per pass, and only where a permission-synced pair's doc sync can run.
    @lru_cache(maxsize=1)
    def doc_multiplier() -> int:
        return int(OnyxRuntime.get_doc_permission_sync_multiplier())

    def read_cadences(row: dict[str, Any]) -> SyncCadences:
        if not row["permission_sync_enabled"]:
            return None, None
        doc: int | None = doc_seconds(
            row["source"], row["status"], row["last_success_at"] is not None
        )
        group: int | None = group_seconds(row["source"], row["status"])
        return (None if doc is None else doc * doc_multiplier()), group

    return read_cadences


def connector_data(row: dict[str, Any], *, cadences: SyncCadences) -> dict[str, Any]:
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
    data: dict[str, Any] = {
        "connector_id": row["connector_id"],
        "cc_pair_id": row["cc_pair_id"],
        "connector_type": row["source"].value.lower(),
        "state": row["status"].value.lower(),
        "doc_count": row["doc_count"] or 0,
        "last_success_at": _iso(row["last_success_at"]),
        "config_hash": fingerprint(json.dumps(metadata, sort_keys=True)),
        "metadata": metadata,
    }
    if row["permission_sync_enabled"]:
        # The doc sync time is the end of the window of source changes it covered;
        # the group sync time is when it finished.
        for key in (
            "last_permission_sync_at",
            "last_group_sync_at",
            "permission_sync_pending_since",
        ):
            if row[key] is not None:
                data[key] = _iso(row[key])
        doc, group = cadences
        if doc is not None:
            data["permission_sync_seconds"] = doc
        if group is not None:
            data["group_sync_seconds"] = group
    return data


def attempt_data(row: dict[str, Any]) -> dict[str, Any]:
    connector_type: str = row["source"].value.lower()
    data: dict[str, Any] = {
        "attempt_id": row["attempt_id"],
        "connector_id": row["connector_id"],
        "cc_pair_id": row["cc_pair_id"],
        "connector_type": connector_type,
        "state": row["status"].value.lower(),
        # An attempt that has not started a batch has no counts yet.
        "docs_indexed": row["docs_indexed"] or 0,
        "chunks_indexed": row["chunks_indexed"] or 0,
        "total_batches": row["total_batches"] or 0,
        "completed_batches": row["completed_batches"] or 0,
        "error_count": row["error_count"] or 0,
        "counter_mode": "snapshot",
        "started_at": _iso(row["started_at"]),
        "last_progress_at": _iso(row["last_progress_at"]),
        "last_heartbeat_at": _iso(row["last_heartbeat_at"]),
    }
    if row["status"].is_terminal():
        data["ended_at"] = _iso(row["ended_at"])
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
    # Only permission and group sync attempts track these.
    for key in ("last_progress_at", "last_heartbeat_at"):
        if row[key] is not None:
            data[key] = _iso(row[key])
    data["error_count"] = max(row["error_count"], int(row["state"] == "failed"))
    # Only a failed run's message says why it failed. A canceled run's message names
    # its internal cause, and a partial doc sync has none.
    if row["state"] == "failed" and row["error_sample"] is not None:
        data["error_code"] = classify_local_error(row["error_sample"])
    if row["started_at"] and row["ended_at"]:
        data["duration_ms"] = max(
            0, (row["ended_at"] - row["started_at"]).total_seconds() * 1000
        )
    return data


def _queue(
    sender: BoundedTelemetry,
    event_type: str,
    data: dict[str, Any],
    tenant_id: str,
    event_id: str | None = None,
    occurred_at: float | None = None,
    revision: int = 0,
) -> bool:
    """Queue one event. False when the sender cannot take a valid event now (a full
    queue or a closed sender), so the next run sends it again. An event that can
    never pass the privacy check counts as handled."""
    if sender.emit(
        event_type,
        data,
        tenant_id=tenant_id,
        event_id=event_id,
        occurred_at=occurred_at,
        revision=revision,
    ):
        return True
    # Only the data decides this, so the sender thread cannot change the answer.
    return sanitize_data(event_type, data) is None


def _send(
    sender: BoundedTelemetry,
    tenant_id: str,
    event_type: str,
    data: dict[str, Any],
    entity: str,
    revision_at: datetime,
    occurred_at: datetime | None = None,
    revision: int = 0,
) -> bool:
    """Queue with an event ID made from the row's identity, the time that identifies
    this state of the row, and the event's revision. The service orders the states
    of one entity by revision, then by event time, which is `revision_at` unless
    `occurred_at` is given."""
    identity: str = f"{tenant_id}:{entity}:{revision_at.isoformat()}"
    # Revision 0 adds nothing, so these events keep the IDs that older versions
    # gave them, and the service drops their repeats across an upgrade.
    if revision:
        identity += f":{revision}"
    if occurred_at is not None:
        # A running job changes its counters without a new revision time.
        identity += ":" + fingerprint(json.dumps(data, sort_keys=True))
    return _queue(
        sender,
        event_type,
        data,
        tenant_id,
        event_id=str(uuid.uuid5(uuid.UUID(str(sender.customer_uuid)), identity)),
        occurred_at=(occurred_at or revision_at).timestamp(),
        revision=revision,
    )


def _send_attempt(
    sender: BoundedTelemetry, tenant_id: str, row: dict[str, Any]
) -> bool:
    """A running attempt goes out at each update, at revision 0. A finished attempt
    goes out at its end, at revision 1 plus its completed batches:

    - Checkpoint cleanup updates finished rows days later. Those sends repeat the
      event ID, revision, and time of the last send, so the service keeps that
      state.
    - Batches still in flight when the attempt ended can complete later and add to
      its counts. Each one raises the revision, so the new counts replace the state.
    - A later write of a final status, the same one or another, stamps a new finish
      time. That send goes out at the new end, at the same revision, and the
      service takes it when the end is later.
    - No other later change gets to the service: a total batch count set after the
      end, errors resolved later, or a status that a bulk update rewrites, such as
      an embedding model swap.
    - The end comes from the worker's clock and can be earlier than the database
      time of the last running snapshot. The service orders states by (generation,
      revision, time), so the finished state still replaces the running one."""
    entity: str = f"attempt:{row['attempt_id']}"
    if not row["status"].is_terminal():
        return _send(
            sender, tenant_id, "attempt", attempt_data(row), entity, row["time_updated"]
        )
    return _send_finished(
        sender,
        tenant_id,
        "attempt",
        attempt_data(row),
        entity,
        row["ended_at"],
        revision=1 + (row["completed_batches"] or 0),
    )


def _send_finished(
    sender: BoundedTelemetry,
    tenant_id: str,
    event_type: str,
    data: dict[str, Any],
    entity: str,
    end: datetime,
    revision: int,
) -> bool:
    """Queue a finished attempt or job at its end. One that ended before the horizon,
    which a later update touched, counts as handled: the service would reject it or
    soon delete it."""
    if end < datetime.now(timezone.utc) - _FINISHED_HORIZON:
        return True
    return _send(sender, tenant_id, event_type, data, entity, end, revision=revision)


def _send_job(
    sender: BoundedTelemetry, tenant_id: str, row: dict[str, Any], started: datetime
) -> bool:
    """A running job goes out at each pass, at revision 0 and at the pass time, so
    its latest counters replace those of an earlier pass, even when its row time is
    from another host's clock or its transaction committed late. A finished job goes
    out at its end, at revision 1:

    - Later passes repeat its event ID, revision, and time, so the service keeps
      that state.
    - A later write of a final status stamps a new end. That send goes out at the
      new end, at the same revision, and the service takes it when the end is later.
    - The service orders the states of a job by revision, then by time, so the
      finished state replaces the running one even when it ended before the last
      running pass. Jobs that end in the same pass keep their own end times.
    - No other later change gets to the service. The event ID comes from the end,
      not the data, so a write that changes a finished row without stamping a new
      end repeats the ID, and the service drops it."""
    end: datetime | None = row["ended_at"]
    if end is None:
        return _send(
            sender,
            tenant_id,
            "job",
            job_data(row),
            row["job_id"],
            row["revision_at"],
            max(row["revision_at"], started),
        )
    return _send_finished(
        sender, tenant_id, "job", job_data(row), row["job_id"], end, revision=1
    )


def _inventory_item(event_type: str, data: dict[str, Any]) -> str:
    if event_type == "connector":
        return f"connector:{data['cc_pair_id']}"
    if event_type == "tenant_domain":
        return f"tenant_domain:{data['domain']}"
    return event_type


class _SentItem(TypedDict):
    digest: str
    sent_at: float


def _send_inventory(
    sender: BoundedTelemetry,
    cache: CacheBackend,
    tenant_id: str,
    inventory: list[tuple[str, dict[str, Any]]],
    now: datetime,
) -> None:
    """Send each inventory item that changed, or whose last send is six hours old.
    Sending only changes keeps a sync time that moves every few minutes from
    resending every connector, domain, and the license each pass."""
    stored: bytes | None = cache.get(_INVENTORY_ITEMS_KEY)
    previous: dict[str, _SentItem] = json.loads(stored) if stored is not None else {}
    sent: dict[str, _SentItem] = {}
    for position, (event_type, data) in enumerate(inventory):
        item: str = _inventory_item(event_type, data)
        digest: str = fingerprint(json.dumps(data, sort_keys=True))[:16]
        last: _SentItem | None = previous.get(item)
        if (
            last is not None
            and last["digest"] == digest
            and now.timestamp() - last["sent_at"] < _INVENTORY_SECONDS
        ):
            sent[item] = last
            continue
        if not _queue(sender, event_type, data, tenant_id):
            # This item and the rest go out in the next run, changed or due.
            for later_type, later_data in inventory[position:]:
                later: str = _inventory_item(later_type, later_data)
                if later in previous:
                    sent[later] = previous[later]
            break
        sent[item] = {"digest": digest, "sent_at": now.timestamp()}
    # Items no longer in the inventory drop out.
    cache.set(_INVENTORY_ITEMS_KEY, json.dumps(sent), ex=_CACHE_SECONDS)


def _send_in_order(
    since: datetime,
    rows: list[dict[str, Any]],
    changed_at: str,
    send: Callable[[dict[str, Any]], bool],
) -> datetime | None:
    """Send rows in read order. Return where the next run must resume: the first
    row that the sender refused, or just after a capped read. Rows from before
    `since` are running work, which every run reads again."""
    for row in rows:
        if not send(row):
            point: datetime = row[changed_at]
            return point if point >= since else None
    if len(rows) < ROW_LIMIT or rows[-1][changed_at] < since:
        return None
    # A capped read moves forward, even when all its rows have the same time.
    return max(rows[-1][changed_at], since + timedelta(microseconds=1))


def stage_data(row: dict[str, Any], attempt: dict[str, Any]) -> dict[str, Any]:
    data: dict[str, Any] = {
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
    data.update(
        connector_id=attempt["connector_id"],
        cc_pair_id=attempt["cc_pair_id"],
        connector_type=attempt["source"].value.lower(),
        stage_name=row["stage"].value,
        first_event_at=_iso(row["first_event_at"]),
        last_event_at=_iso(row["last_event_at"]),
    )
    return data


def _jitter(low: float, high: float) -> float:
    return random.uniform(low, high)


def _week_of(at: datetime) -> date:
    day: date = at.astimezone(timezone.utc).date()
    return day - timedelta(days=day.weekday())


def _read_or_none(db_session: Session, read: Callable[[], Any]) -> Any:
    """Run one read in a savepoint. A read that fails, for example on the statement
    timeout, returns None and leaves the transaction usable for the next read."""
    try:
        with db_session.begin_nested():
            return read()
    except Exception:
        return None


def setup_data(
    counts: dict[str, int], providers: list[tuple[str, int]]
) -> dict[str, Any]:
    """Setup counts. Provider types outside Onyx's list count as custom."""
    by_type: dict[str, int] = {}
    for provider, count in providers:
        kind: str = provider if provider in _LLM_PROVIDER_TYPES else "custom"
        by_type[kind] = by_type.get(kind, 0) + count
    return {
        **counts,
        "llm_providers": by_type,
        # Cloud's Google login is the same for every tenant, so only rows count there.
        "sso_configured": counts["sso_providers"] > 0
        or (OAUTH_ENABLED and not MULTI_TENANT),
    }


class _HistoryState(TypedDict):
    # The oldest week not sent yet in this cycle; None until the first question is read.
    next_week: str | None
    cycle_started_at: float
    due_at: float


def _send_usage_history(
    sender: BoundedTelemetry,
    cache: CacheBackend,
    db_session: Session,
    tenant_id: str,
    state: _HistoryState,
    now: datetime,
) -> bool:
    """Send the next few completed weeks. False when a read failed."""
    current_week: date = _week_of(now)
    state["due_at"] = now.timestamp() + _jitter(*_HISTORY_GAP_SECONDS)
    ok: bool = True
    if state["next_week"] is None:
        first: Any = _read_or_none(db_session, lambda: (first_question_at(db_session),))
        if first is None:
            ok = False
        elif first[0] is None:
            # No question yet: the first one is in this week or later.
            state["next_week"] = current_week.isoformat()
        else:
            state["next_week"] = max(_week_of(first[0]), _EARLIEST_WEEK).isoformat()
    if state["next_week"] is not None:
        start: date = date.fromisoformat(state["next_week"])
        end: date = min(start + timedelta(weeks=_HISTORY_WEEKS_PER_READ), current_week)
        if start < end:
            rows: Any = _read_or_none(
                db_session, lambda: usage_week_rows(db_session, start, end)
            )
            if rows is None:
                ok = False
            else:
                by_week = {row.week_start: row for row in rows}
                week: date = start
                while week < end:
                    row = by_week.get(week)
                    data: dict[str, Any] = {
                        "week_start": week.isoformat(),
                        "queries": row.queries if row else 0,
                        "sessions": row.sessions if row else 0,
                        "active_users": row.active_users if row else 0,
                    }
                    if not _queue(sender, "usage_week", data, tenant_id):
                        break
                    week += timedelta(weeks=1)
                # A full queue stops here; the next read resumes at this week.
                state["next_week"] = week.isoformat()
    cache.set(_HISTORY_KEY, json.dumps(state), ex=_CACHE_SECONDS)
    return ok


def collect_usage(
    sender: BoundedTelemetry, cache: CacheBackend, tenant_id: str, now: datetime
) -> None:
    """Usage and setup counts about once an hour, and the next weeks of history.
    Each read runs only when it is due, so most passes read nothing here."""
    stored: bytes | None = cache.get(_USAGE_DUE_KEY)
    if stored is None:
        usage_due_at: float = now.timestamp() + _jitter(0, _USAGE_SECONDS)
        cache.set(_USAGE_DUE_KEY, str(usage_due_at), ex=_CACHE_SECONDS)
    else:
        usage_due_at = float(stored)
    history: bytes | None = cache.get(_HISTORY_KEY)
    state: _HistoryState
    if history is None:
        state = {
            "next_week": None,
            "cycle_started_at": now.timestamp(),
            "due_at": now.timestamp() + _jitter(0, _USAGE_SECONDS),
        }
        cache.set(_HISTORY_KEY, json.dumps(state), ex=_CACHE_SECONDS)
    else:
        state = json.loads(history)
        if (
            now.timestamp() - state["cycle_started_at"]
            > _HISTORY_REFRESH.total_seconds()
        ):
            state["next_week"] = None
            state["cycle_started_at"] = now.timestamp()
    history_due: bool = state["due_at"] <= now.timestamp() and (
        state["next_week"] is None
        or date.fromisoformat(state["next_week"]) < _week_of(now)
    )
    usage_due: bool = usage_due_at <= now.timestamp()
    if not usage_due and not history_due:
        return
    failures: int = 0
    with get_session_with_tenant(tenant_id=tenant_id) as db_session:
        limit_statement_time(db_session)
        if usage_due:
            cache.set(
                _USAGE_DUE_KEY,
                str(
                    now.timestamp() + _USAGE_SECONDS + _jitter(0, _USAGE_JITTER_SECONDS)
                ),
                ex=_CACHE_SECONDS,
            )
            usage: Any = _read_or_none(
                db_session, lambda: usage_counts(db_session, now)
            )
            if usage is None:
                failures += 1
            else:
                _queue(sender, "usage", usage, tenant_id)
            setup: Any = _read_or_none(db_session, lambda: setup_counts(db_session))
            if setup is None:
                failures += 1
            else:
                _queue(sender, "setup", setup_data(*setup), tenant_id)
        if history_due and not _send_usage_history(
            sender, cache, db_session, tenant_id, state, now
        ):
            failures += 1
    if failures:
        sender.health["usage_errors"] = sender.health.get("usage_errors", 0) + failures


def collect_snapshots(tenant_id: str) -> None:
    """One collection pass for one tenant. Never raises."""
    sender: BoundedTelemetry | None = get_sender()
    # Event IDs live in the namespace that enrollment assigns.
    if sender is None or sender.customer_uuid is None:
        return
    started: datetime = datetime.now(timezone.utc)
    try:
        cache: CacheBackend = get_cache_backend(tenant_id=tenant_id)
        cursor: bytes | None = cache.get(_CURSOR_KEY)
        since: datetime = (
            max(datetime.fromisoformat(cursor.decode()), started - _MAX_WINDOW)
            if cursor is not None
            else started - _FIRST_WINDOW
        )
        with get_session_with_tenant(tenant_id=tenant_id) as db_session:
            limit_statement_time(db_session)
            has_indexed_connectors = has_indexed_connectors__no_commit(db_session)
            read_cadences: Callable[[dict[str, Any]], SyncCadences] = (
                permission_sync_cadence_reader()
            )
            inventory: list[tuple[str, dict[str, Any]]] = [
                ("connector", connector_data(row, cadences=read_cadences(row)))
                for row in connector_rows(db_session)
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
            users = standard_user_counts(db_session)
            inventory.append(("users", {"total": users.total, "active": users.active}))
            attempts: list[dict[str, Any]] = attempt_rows(db_session, since)
            stages: list[dict[str, Any]] = stage_rows(
                db_session, [row["attempt_id"] for row in attempts], since
            )
            jobs: list[dict[str, Any]] = job_rows(db_session, since)
        by_attempt: dict[int, dict[str, Any]] = {
            row["attempt_id"]: row for row in attempts
        }
        resume: list[datetime | None] = [
            _send_in_order(
                since,
                attempts,
                "time_updated",
                lambda row: _send_attempt(sender, tenant_id, row),
            ),
            # The service requires the event time to equal the summary's last update.
            _send_in_order(
                since,
                stages,
                "last_event_at",
                lambda row: _send(
                    sender,
                    tenant_id,
                    "stage",
                    stage_data(row, by_attempt[row["attempt_id"]]),
                    f"stage:{row['attempt_id']}:{row['stage'].value}",
                    row["last_event_at"],
                ),
            ),
        ]
        # Each job table is a separate capped read.
        for _, table in groupby(jobs, key=lambda row: row["job_id"].split(":")[0]):
            resume.append(
                _send_in_order(
                    since,
                    list(table),
                    "revision_at",
                    lambda row: _send_job(sender, tenant_id, row, started),
                ),
            )
        # Work goes first, so a large inventory cannot hold it back.
        sender.emit(
            "heartbeat",
            {
                # Workers can have different Lite settings from the API.
                **(
                    {"deployment_type": DEPLOYMENT_TYPE.value}
                    if sender.service == "api"
                    else {}
                ),
                "has_indexed_connectors": has_indexed_connectors,
            },
            tenant_id=tenant_id,
        )
        _send_inventory(sender, cache, tenant_id, inventory, started)
        next_since: datetime = min(
            [started - _OVERLAP, *(point for point in resume if point is not None)]
        )
        cache.set(_CURSOR_KEY, next_since.isoformat(), ex=_CACHE_SECONDS)
        sender.health["source_consecutive_errors"] = 0
        sender.health["last_source_success_at"] = started.isoformat()
        try:
            collect_usage(sender, cache, tenant_id, started)
        except Exception:
            sender.health["usage_errors"] = sender.health.get("usage_errors", 0) + 1
    except Exception:
        # No SQL, identifiers, or exception text leave the process.
        sender.health["source_errors"] = sender.health.get("source_errors", 0) + 1
        sender.health["source_consecutive_errors"] = (
            sender.health.get("source_consecutive_errors", 0) + 1
        )
