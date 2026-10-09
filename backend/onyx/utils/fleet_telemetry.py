"""Bounded, lossy fleet telemetry. Application threads never perform telemetry I/O."""

import gzip
import hashlib
import json
import math
import os
import re
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any

import requests

from onyx.configs.app_configs import DISABLE_TELEMETRY, WEB_DOMAIN
from onyx.configs.constants import OnyxCeleryQueues
from shared_configs.configs import MULTI_TENANT
from shared_configs.contextvars import get_current_tenant_id

_ENDPOINT: str = (
    os.environ.get("ONYX_TELEMETRY_ENDPOINT") or "https://telemetry.onyx.app"
).rstrip("/")
# Every string value must be one short token. Spaces, slashes, and "@" cannot
# pass, so free text, paths, URLs, and email addresses never leave the process.
_TOKEN: re.Pattern[str] = re.compile(r"[A-Za-z0-9_.:+-]{1,128}\Z")
_OPAQUE: re.Pattern[str] = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")
_VERSION: re.Pattern[str] = re.compile(
    r"(?:v?\d{1,4}\.\d{1,4}(?:\.\d{1,4})?(?:[-.](?:cloud|beta|alpha|rc|dev|nightly|release)(?:[-.]?\d{1,8})?){0,3}|[a-f0-9]{7,40}|unknown|dev|nightly)\Z"
)

# Read from OnyxCeleryQueues, so a renamed queue needs no telemetry change.
CELERY_QUEUES: tuple[str, ...] = tuple(
    value
    for key, value in vars(OnyxCeleryQueues).items()
    if not key.startswith("_") and isinstance(value, str)
)
# Connector configuration keys exported only as reviewed booleans and numbers.
SAFE_BOOLEAN_SETTINGS: tuple[str, ...] = (
    "include_shared_drives",
    "include_my_drives",
    "include_files_shared_with_me",
    "exclude_domain_link_only",
    "include_shared",
    "follow_shortcuts",
    "only_org_public",
    "continue_on_failure",
    "include_attachments",
    "include_calendar",
    "include_bot_messages",
    "channel_regex_enabled",
    "exclude_channel_regex_enabled",
    "index_recursively",
    "recursive_index_enabled",
    "include_mrs",
    "include_issues",
    "include_code_files",
    "include_web_links",
    "index_page_content",
    "retrieve_task_comments",
    "allow_images",
    "include_inline_images",
    "include_meeting_transcripts",
    "include_meeting_chats",
    "include_article",
    "include_blog",
    "include_wiki",
    "include_forum",
    "hide_user_info",
    "european_residency",
)
SAFE_NUMBER_SETTINGS: tuple[str, ...] = (
    "batch_size",
    "num_threads",
    "max_workers",
    "recurse_depth",
    "max_pages",
    "cases_page_size",
    "skip_doc_absolute_chars",
    "calendar_past_days",
    "calendar_future_days",
    "experiment_row_lookback_days",
)
# Counts and flags derived from connector configuration.
CONNECTOR_CONFIG_COUNTS: tuple[str, ...] = ("selection_count", "has_time_filter")
# Scheduling and sync settings read from connector columns.
CONNECTOR_ROW_SETTINGS: tuple[str, ...] = (
    "refresh_seconds",
    "prune_seconds",
    "auto_sync_enabled",
    "permission_sync_enabled",
)
# Nested maps: their values must be numbers or booleans.
_NESTED_FIELDS: dict[str, frozenset[str]] = {
    "metadata": frozenset(
        SAFE_BOOLEAN_SETTINGS
        + SAFE_NUMBER_SETTINGS
        + CONNECTOR_CONFIG_COUNTS
        + CONNECTOR_ROW_SETTINGS
    ),
    "counters": frozenset(
        {
            "fetch_docs",
            "fetch_errors",
            "embed_chunks",
            "embed_errors",
            "write_chunks",
            "write_errors",
        }
    ),
}
# The keys each event type may carry. The fleet service checks the values.
_FIELDS: dict[str, frozenset[str]] = {
    "stage": frozenset(
        {
            "attempt_id",
            "connector_id",
            "cc_pair_id",
            "connector_type",
            "stage_name",
            "event_count",
            "total_duration_ms",
            "min_duration_ms",
            "max_duration_ms",
            "m2_duration_ms",
            "first_event_at",
            "last_event_at",
        }
    ),
    "license": frozenset({"license_present", "first_set_at"}),
    "tenant_domain": frozenset({"domain", "first_signup_at"}),
    "query": frozenset(
        {
            "query_id",
            "channel",
            "mode",
            "outcome",
            "first_answer_ms",
            "time_to_results_ms",
            "error_code",
        }
    ),
    "connector": frozenset(
        {
            "connector_id",
            "cc_pair_id",
            "connector_type",
            "state",
            "doc_count",
            "config_hash",
            "metadata",
            "last_success_at",
        }
    ),
    "attempt": frozenset(
        {
            "attempt_id",
            "connector_id",
            "cc_pair_id",
            "connector_type",
            "state",
            "docs_indexed",
            "chunks_indexed",
            "total_batches",
            "completed_batches",
            "error_count",
            "error_code",
            "error_fingerprint",
            "counters",
            "counter_mode",
            "stage",
            "duration_ms",
            "started_at",
            "ended_at",
            "last_progress_at",
            "last_heartbeat_at",
        }
    ),
    "job": frozenset(
        {
            "job_id",
            "job_type",
            "state",
            "docs_processed",
            "duration_ms",
            "error_count",
            "started_at",
            "ended_at",
            "entity_id",
            "cc_pair_id",
            "users_processed",
            "groups_processed",
            "memberships_synced",
        }
    ),
    "queue": frozenset({"queue", "depth", "shared"}),
    "resource": frozenset(
        {
            "opensearch_status",
            "opensearch_checked_at",
            "opensearch_resource_checked_at",
            "opensearch_resource_stale",
            "opensearch_disk_pressure",
            "opensearch_heap_pressure",
            "opensearch_vector_pressure",
            "opensearch_number_of_nodes",
            "opensearch_number_of_data_nodes",
            "opensearch_active_shards",
            "opensearch_unassigned_shards",
            "opensearch_initializing_shards",
            "opensearch_relocating_shards",
            "opensearch_number_of_pending_tasks",
            "service_instance_id",
            "memory_bytes",
            "memory_limit_bytes",
            "disk_bytes",
            "disk_limit_bytes",
            "cpu_cores",
            "cpu_limit_cores",
            "cpu_throttled_seconds",
            "shared",
        }
    ),
    "runtime": frozenset({"service_instance_id", "reason"}),
    "version": frozenset({"version"}),
    "heartbeat": frozenset(
        {
            "dropped_events",
            "recent_dropped_events",
            "rejected_events",
            "invalid_events",
            "spool_events",
            "source_errors",
            "source_consecutive_errors",
            "last_source_success_at",
        }
    ),
}

# Collection schedule. The fleet service cannot change it.
COLLECTION_INTERVAL_SECONDS: int = 300
QUEUE_INTERVAL_SECONDS: int = 600
RESOURCE_INTERVAL_SECONDS: int = 300

# Delivery bounds. The fleet service accepts up to 500 events per request.
_BATCH_SIZE: int = 100
_FLUSH_SECONDS: float = 2.0
_MAX_BATCHES_PER_WAKEUP: int = 5
_FINAL_FLUSH_SECONDS: float = 5.0
# The service asks to send an event again when it could not store it yet. The
# sender sends such an event at most this many more times.
_MAX_RETRIES: int = 3
# Short-lived processes wait at most this long at exit for their final delivery.
EXIT_FLUSH_SECONDS: float = 2.0
# Indexing counter deltas are summed per attempt and stage for this long.
_STAGE_WINDOW_SECONDS: float = 30.0
_MAX_STAGE_KEYS: int = 256


def fingerprint(value: str) -> str:
    """A hex digest, so names and raw values never leave the process."""
    return hashlib.sha256(value.encode()).hexdigest()


def is_valid_version(value: str) -> bool:
    """Accept only bounded release tags, build hashes, and fixed version labels."""
    return _VERSION.fullmatch(value) is not None


def read_json_body(response: requests.Response, limit: int) -> Any:
    """Parse an uncompressed JSON body of at most `limit` bytes. Raise otherwise.

    Like json.loads, the result is unvalidated; callers check its structure."""
    if response.headers.get("Content-Encoding", "identity") not in {"", "identity"}:
        raise ValueError("Unsupported response encoding")
    raw: bytes = response.raw.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("Response exceeds limit")
    return json.loads(raw)


def _is_number(value: object) -> bool:
    return isinstance(value, (bool, int, float)) and math.isfinite(value) and value >= 0


def sanitize_data(event_type: str, data: dict[str, Any]) -> dict[str, Any] | None:
    """Keep reviewed keys with numbers, booleans, or short tokens. Reject the rest."""
    allowed: frozenset[str] | None = _FIELDS.get(event_type)
    if allowed is None or not data.keys() <= allowed:
        return None
    safe: dict[str, Any] = {}
    for key, value in data.items():
        nested: frozenset[str] | None = _NESTED_FIELDS.get(key)
        if nested is not None:
            if not isinstance(value, dict) or not value.keys() <= nested:
                return None
            if not all(item is None or _is_number(item) for item in value.values()):
                return None
            safe[key] = dict(value)
        elif (
            value is None
            or _is_number(value)
            or (isinstance(value, str) and _TOKEN.fullmatch(value))
        ):
            safe[key] = value
        else:
            return None
    return safe


def deployment_key() -> str:
    """The deployment's stable key. The fleet service takes it as a write credential."""
    if MULTI_TENANT:
        # Cloud has no instance-level key-value store. Its web domain names it.
        return fingerprint("onyx-cloud:" + WEB_DOMAIN)
    from onyx.db.fleet_enrollment import get_or_create_deployment_key

    return get_or_create_deployment_key()


class BoundedTelemetry:
    """One daemon thread per process. A full queue sheds events; emitters never wait."""

    def __init__(
        self,
        service: str = "api",
        *,
        report_process: bool = True,
        capacity: int = 2048,
    ) -> None:
        self.service: str = service
        self.capacity: int = capacity
        # Short-lived processes deliver hook events only; their parent reports the process.
        self.report_process: bool = report_process
        self.pid: int = os.getpid()
        # One ID for this process's runtime and resource events.
        self.instance_id: str = fingerprint(f"{self.pid}:{os.uname().nodename}")
        # deque append/popleft are thread-safe, so emitters take no lock.
        self._queue: deque[
            tuple[str, dict[str, Any], str | None, float, str | None, str]
        ] = deque()
        self._stop: threading.Event = threading.Event()
        self._thread: threading.Thread | None = None
        self.sent: int = 0
        self.dropped: int = 0
        self.rejected: int = 0
        self.invalid: int = 0
        self._dropped_at_heartbeat: int = 0
        self.failures: int = 0
        self._blocked_until: float = 0.0
        # The batch in flight. An outage keeps it for the next attempt.
        self._pending: list[dict[str, Any]] = []
        self._retries: int = 0
        self._session: requests.Session | None = None
        # The sender thread reads the key and enrolls before its first delivery.
        self._key: str | None = None
        self._customer: str | None = None
        self._deployment: str | None = None
        self._stage_sums: dict[tuple[str, ...], dict[str, Any]] = {}
        self._last_stage_flush: float = time.monotonic()
        # Source read counts that a collecting process adds to its heartbeat.
        self.health: dict[str, Any] = {}

    def emit(
        self,
        event_type: str,
        data: dict[str, Any],
        *,
        tenant_id: str | None = None,
        event_id: str | None = None,
        occurred_at: float | None = None,
        service: str | None = None,
    ) -> bool:
        """No locks, thread creation, serialization, logging, network, disk, or database calls."""
        try:
            if self.pid != os.getpid() or self._stop.is_set():
                return False
            safe: dict[str, Any] | None = sanitize_data(event_type, data)
            if safe is None:
                self.invalid += 1
                self.dropped += 1
                return False
            # Concurrent emitters can overshoot the capacity by at most one event each.
            if len(self._queue) >= self.capacity:
                self.dropped += 1
                return False
            self._queue.append(
                (
                    event_type,
                    safe,
                    tenant_id,
                    occurred_at if occurred_at is not None else time.time(),
                    event_id,
                    service or self.service,
                )
            )
            return True
        except Exception:
            self.dropped += 1
            return False

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run, name="fleet-telemetry-sender", daemon=True
        )
        self._thread.start()

    def close(self, flush_timeout: float = 0.0) -> None:
        """Stop accepting events. The sender makes one bounded final delivery attempt;
        callers wait for it at most `flush_timeout` seconds (default: not at all)."""
        self._stop.set()
        thread: threading.Thread | None = self._thread
        if (
            flush_timeout > 0
            and thread is not None
            and thread is not threading.current_thread()
        ):
            thread.join(flush_timeout)

    @property
    def closed(self) -> bool:
        return self._stop.is_set()

    @property
    def customer_uuid(self) -> str | None:
        """The ID that the fleet service assigned at enrollment. None until then."""
        return self._customer

    @property
    def deployment_id(self) -> str | None:
        """The deployment ID that the fleet service assigned. None until enrollment."""
        return self._deployment

    def _take_batch(self) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for _ in range(_BATCH_SIZE):
            try:
                event_type, data, tenant, occurred_at, event_id, service = (
                    self._queue.popleft()
                )
            except IndexError:
                break
            try:
                events.append(
                    self._envelope(
                        event_type, data, tenant, occurred_at, event_id, service
                    )
                )
            except Exception:
                # One malformed entry is dropped without losing the rest of the batch.
                self.dropped += 1
        return events

    def _envelope(
        self,
        event_type: str,
        data: dict[str, Any],
        tenant: str | None,
        occurred_at: float,
        event_id: str | None,
        service: str,
    ) -> dict[str, Any]:
        if self._customer is None or self._deployment is None:
            raise RuntimeError("Fleet enrollment is not complete")
        customer: str = self._customer
        scope: str | None = None
        # Each Cloud tenant reports as its own customer inside this deployment.
        # Shared events describe the whole deployment.
        if MULTI_TENANT and tenant and not data.get("shared"):
            scope = str(uuid.uuid5(uuid.NAMESPACE_X500, tenant))
            customer = str(uuid.uuid5(uuid.UUID(customer), scope))
        return {
            "schema_version": 2,
            "event_id": event_id or str(uuid.uuid4()),
            "event_type": event_type,
            "occurred_at": datetime.fromtimestamp(
                occurred_at, timezone.utc
            ).isoformat(),
            "customer_uuid": customer,
            "deployment_id": self._deployment,
            **({"installation_scope": scope} if scope else {}),
            "service": service,
            "is_cloud": MULTI_TENANT,
            "data": data,
        }

    def flush_once(self, transport: Any = None) -> bool:
        """Send one batch. True when it was delivered or nothing was due.

        The service answers with how many events it accepted and rejected, and
        which events to send again. The sender sends those again after a backoff,
        at most `_MAX_RETRIES` times. It counts all other events as dropped.
        """
        if time.monotonic() < self._blocked_until:
            return False
        if not (self._pending or self._queue or self._stage_sums):
            return True
        try:
            if transport is None:
                if self._session is None:
                    self._session = requests.Session()
                transport = self._session.post
            if self._deployment is None:
                self._enroll(transport)
            if not self._pending:
                self._pending = self._sum_stages(self._take_batch())
            if not self._pending:
                return True
            response: requests.Response = transport(
                _ENDPOINT + "/v1/events",
                headers={
                    "Authorization": "Bearer " + str(self._key),
                    "Content-Type": "application/json",
                    "Accept-Encoding": "identity",
                    "Content-Encoding": "gzip",
                },
                data=gzip.compress(
                    json.dumps(
                        {"events": self._pending}, separators=(",", ":")
                    ).encode(),
                    compresslevel=1,
                    mtime=0,
                ),
                timeout=(1, 2),
                allow_redirects=False,
                stream=True,
            )
            with response:
                if response.status_code == 401:
                    # The service no longer knows the key. Enroll again.
                    self._deployment = None
                if response.status_code in {400, 413, 422}:
                    # Sending the same batch again cannot succeed.
                    self.rejected += len(self._pending)
                    self.dropped += len(self._pending)
                    self._pending = []
                if not response.ok:
                    raise RuntimeError("telemetry delivery failed")
                result: Any = read_json_body(response, 65536)
        except Exception:
            # An outage keeps the batch and backs off.
            self._back_off()
            return False
        counts: dict[str, Any] = result if isinstance(result, dict) else {}
        retry: list[dict[str, Any]] = self._retry_events(counts.get("results"))
        sent: Any = counts.get("accepted")
        rejected: Any = counts.get("rejected")
        sent = sent if type(sent) is int else len(self._pending) - len(retry)
        rejected = rejected if type(rejected) is int else 0
        self.sent += sent
        self.rejected += rejected
        if retry and self._retries < _MAX_RETRIES:
            self._retries += 1
            self.dropped += max(0, len(self._pending) - sent - len(retry))
            self._pending = retry
            self._back_off()
            return False
        self.failures = 0
        self._retries = 0
        self.dropped += max(0, len(self._pending) - sent)
        self._pending = []
        return True

    def _back_off(self) -> None:
        self.failures = min(self.failures + 1, 8)
        self._blocked_until = time.monotonic() + min(300, 2**self.failures)

    def _retry_events(self, results: Any) -> list[dict[str, Any]]:
        """The events of the batch that the service asks to send again."""
        if not isinstance(results, list):
            return []
        indexes: set[int] = {
            row["index"]
            for row in results
            if isinstance(row, dict)
            and row.get("status") == "retry"
            and type(row.get("index")) is int
        }
        return [event for index, event in enumerate(self._pending) if index in indexes]

    def _enroll(self, transport: Any) -> None:
        """Register the deployment key. The service answers with this deployment's IDs."""
        if self._key is None:
            self._key = deployment_key()
        response: requests.Response = transport(
            _ENDPOINT + "/v1/enroll",
            headers={
                "Authorization": "Bearer " + self._key,
                "Accept-Encoding": "identity",
            },
            json={"is_cloud": MULTI_TENANT},
            timeout=(1, 2),
            allow_redirects=False,
            stream=True,
        )
        with response:
            if response.status_code != 200:
                raise ValueError("Fleet enrollment unavailable")
            result: Any = read_json_body(response, 4096)
        deployment: Any = result["deployment_id"]
        if not isinstance(deployment, str) or not _OPAQUE.fullmatch(deployment):
            raise ValueError("Invalid fleet deployment ID")
        self._customer = str(uuid.UUID(result["customer_uuid"]))
        self._deployment = deployment

    def _sum_stages(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Sum counter deltas per attempt and stage. Release the sums every window."""
        ready: list[dict[str, Any]] = []
        for event in events:
            data: dict[str, Any] = event["data"]
            if event["event_type"] != "attempt" or data.get("counter_mode") != "delta":
                ready.append(event)
                continue
            key: tuple[str, ...] = (
                event["customer_uuid"],
                event["service"],
                str(data.get("attempt_id")),
                str(data.get("stage")),
            )
            total: dict[str, Any] = self._stage_sums.setdefault(key, event)
            if total is not event:
                summed: dict[str, Any] = total["data"]
                counters: dict[str, Any] = summed.setdefault("counters", {})
                for name, value in (data.get("counters") or {}).items():
                    counters[name] = (counters.get(name) or 0) + (value or 0)
                summed["duration_ms"] = (summed.get("duration_ms") or 0) + (
                    data.get("duration_ms") or 0
                )
        now: float = time.monotonic()
        # A closed sender has no later window, so it releases every sum now.
        if (
            self._stop.is_set()
            or now - self._last_stage_flush >= _STAGE_WINDOW_SECONDS
            or len(self._stage_sums) > _MAX_STAGE_KEYS
        ):
            ready.extend(self._stage_sums.values())
            self._stage_sums = {}
            self._last_stage_flush = now
        return ready

    def delivery_health(self) -> dict[str, int]:
        """Loss totals, and the loss since the previous heartbeat."""
        dropped: int = self.dropped
        recent: int = dropped - self._dropped_at_heartbeat
        self._dropped_at_heartbeat = dropped
        return {
            "dropped_events": dropped,
            "recent_dropped_events": recent,
            "rejected_events": self.rejected,
            "invalid_events": self.invalid,
            "spool_events": len(self._queue)
            + len(self._pending)
            + len(self._stage_sums),
        }

    def _report_start(self) -> None:
        self.emit(
            "runtime", {"service_instance_id": self.instance_id, "reason": "started"}
        )
        from onyx import __version__

        version: str = "dev" if __version__ == "Development" else __version__
        self.emit(
            "version", {"version": version if is_valid_version(version) else "unknown"}
        )

    def _run(self) -> None:
        last_resource: float | None = None
        try:
            if self.report_process:
                self._report_start()
            while not self._stop.is_set():
                try:
                    now: float = time.monotonic()
                    if self.report_process and poll_due(
                        last_resource, now, RESOURCE_INTERVAL_SECONDS
                    ):
                        from onyx.utils.fleet_telemetry_resources import (
                            collect_process_resource,
                        )

                        collect_process_resource(self)
                        self.emit(
                            "heartbeat", {**self.delivery_health(), **self.health}
                        )
                        last_resource = now
                    # A backlog drains in consecutive batches; an idle queue sends nothing.
                    for _ in range(_MAX_BATCHES_PER_WAKEUP):
                        if not self.flush_once() or len(self._queue) < _BATCH_SIZE:
                            break
                except Exception:
                    # One failed iteration never ends delivery for the process.
                    pass
                self._stop.wait(_FLUSH_SECONDS)
            self._final_flush()
        except Exception:
            # Telemetry failure never reaches the application, including initialization.
            pass
        finally:
            if self._session is not None:
                self._session.close()

    def _final_flush(self) -> None:
        """Release summed counters and send what remains while delivery is healthy.

        Short-lived processes (e.g. spawned indexing children) otherwise exit with
        their final counters still inside the summing window. A failed or
        backed-off delivery ends the attempt immediately.
        """
        deadline: float = time.monotonic() + _FINAL_FLUSH_SECONDS
        while (
            self._queue or self._pending or self._stage_sums
        ) and time.monotonic() < deadline:
            if not self.flush_once():
                return


def poll_due(previous: float | None, now: float, interval: float) -> bool:
    """Poll immediately before the first attempt, regardless of host uptime."""
    return previous is None or now - previous >= interval


_client: BoundedTelemetry | None = None


def start_telemetry(
    service: str = "api", *, report_process: bool = True
) -> BoundedTelemetry | None:
    """Start this process's sender thread. Never waits for the database or network.

    `report_process=False` suits short-lived processes: they deliver hook events
    without startup, resource, or heartbeat reports of their own.
    """
    global _client
    if DISABLE_TELEMETRY:
        return None
    try:
        if _client is None or _client.pid != os.getpid() or _client.closed:
            _client = BoundedTelemetry(service, report_process=report_process)
            _client.start()
        return _client
    except Exception:
        return None


def stop_telemetry(flush_timeout: float = 0.0) -> None:
    """Stop sending. Waits at most `flush_timeout` for a final delivery."""
    client: BoundedTelemetry | None = _client
    if client is not None:
        client.close(flush_timeout)


def get_sender() -> BoundedTelemetry | None:
    """This process's running sender, or None when telemetry is off or stopped."""
    client: BoundedTelemetry | None = _client
    if client is None or client.pid != os.getpid() or client.closed:
        return None
    return client


def emit_telemetry(
    event_type: str,
    data: dict[str, Any],
    *,
    tenant_id: str | None = None,
    service: str | None = None,
) -> bool:
    try:
        client: BoundedTelemetry | None = _client
        if client is None:
            return False
        return client.emit(
            event_type,
            data,
            tenant_id=tenant_id or get_current_tenant_id(),
            service=service,
        )
    except Exception:
        return False


def emit_stage_counter(
    attempt_id: int | None,
    stage: str,
    counters: dict[str, int],
    *,
    duration_ms: int = 0,
    tenant_id: str | None = None,
) -> None:
    if attempt_id is not None:
        emit_telemetry(
            "attempt",
            {
                "attempt_id": attempt_id,
                "stage": stage,
                "counter_mode": "delta",
                "counters": counters,
                "duration_ms": duration_ms,
            },
            tenant_id=tenant_id,
        )


def error_category(error: BaseException) -> str:
    """Classify by known exception type names. Never inspect exception text/arguments."""
    name: str = type(error).__name__
    if name in {"TimeoutError", "ReadTimeout", "ConnectTimeout", "APITimeoutError"}:
        return "timeout"
    if name in {"AuthenticationError", "AuthError"}:
        return "auth"
    if name in {"PermissionError", "PermissionDeniedError"}:
        return "permission"
    if name == "RateLimitError":
        return "rate_limit"
    if name in {"BulkIndexError", "OpenSearchIndexError", "TransportError"}:
        return "index_write"
    if name in {"ConnectionError", "APIConnectionError", "ConnectionTimeout"}:
        return "source_unavailable"
    return "internal"
