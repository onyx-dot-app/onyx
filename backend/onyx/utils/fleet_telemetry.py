"""Bounded, lossy fleet telemetry. Application threads never perform telemetry I/O."""

import gzip
import hashlib
import hmac
import json
import math
import os
import re
import threading
import time
import uuid
from collections import OrderedDict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import SplitResult, urlsplit

import requests

from onyx.configs.constants import DocumentSource, OnyxCeleryQueues
from onyx.db.index_attempt_metrics_models import IndexAttemptStage
from shared_configs.configs import MULTI_TENANT
from shared_configs.contextvars import get_current_tenant_id

_HEX: re.Pattern[str] = re.compile(r"[a-f0-9]{64}\Z")
_EMAIL_DOMAIN: re.Pattern[str] = re.compile(
    r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?\Z"
)
_OPAQUE: re.Pattern[str] = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")
_VERSION: re.Pattern[str] = re.compile(
    r"(?:v?\d{1,4}\.\d{1,4}(?:\.\d{1,4})?(?:[-.](?:cloud|beta|alpha|rc|dev|nightly|release)(?:[-.]?\d{1,8})?){0,3}|[a-f0-9]{7,40}|unknown|dev|nightly)\Z"
)

_STATES: frozenset[str] = frozenset(
    {
        "not_started",
        "in_progress",
        "success",
        "failed",
        "completed_with_errors",
        "canceled",
        "interrupted",
        "scheduled",
        "initial_indexing",
        "active",
        "paused",
        "deleting",
        "invalid",
        "unknown",
    }
)
_ERRORS: frozenset[str] = frozenset(
    {
        "auth",
        "permission",
        "rate_limit",
        "timeout",
        "source_unavailable",
        "parse",
        "embedding",
        "index_write",
        "storage",
        "internal",
        "unknown",
    }
)
_SOURCES: frozenset[str] = frozenset(source.value for source in DocumentSource)
_QUEUES: frozenset[str] = frozenset(
    value
    for key, value in vars(OnyxCeleryQueues).items()
    if not key.startswith("_") and isinstance(value, str)
)
_JOB_TYPES: frozenset[str] = frozenset(
    {
        "document_set",
        "user_group",
        "connector_deletion",
        "pruning",
        "external_permissions",
        "external_group",
        "permission_sync",
        "group_sync",
        "metadata",
        "hierarchy",
        "file_processing",
        "migration",
        "unknown",
    }
)
_SERVICES: frozenset[str] = frozenset(
    {
        "api",
        "worker",
        "collector",
        "scheduler",
        "indexing",
        "background",
        "web",
        "slack",
        "discord",
        "opensearch",
        "vespa",
        "postgres",
        "redis",
        "unknown",
    }
)
_METADATA: frozenset[str] = frozenset(
    {
        "refresh_seconds",
        "prune_seconds",
        "auto_sync_enabled",
        "permission_sync_enabled",
        "selection_count",
        "include_rule_count",
        "exclude_rule_count",
        "include_pattern_count",
        "exclude_pattern_count",
        "has_time_filter",
        "file_type_count",
        "scope_hashes_count",
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
    }
)
_COUNTERS: frozenset[str] = frozenset(
    {
        "fetch_docs",
        "fetch_bytes",
        "fetch_requests",
        "fetch_errors",
        "fetch_throttles",
        "prepare_docs",
        "prepare_chunks",
        "embed_chunks",
        "embed_errors",
        "embed_throttles",
        "write_docs",
        "write_chunks",
        "write_errors",
        "write_rejected",
        "pending_fetch_docs",
        "pending_embed_chunks",
        "pending_write_chunks",
        "oldest_pending_seconds",
    }
)
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
    "license": frozenset({"license_present", "action", "first_set_at"}),
    "tenant_domain": frozenset({"domain", "first_signup_at"}),
    "query": frozenset(
        {
            "query_id",
            "channel",
            "mode",
            "outcome",
            "total_ms",
            "latency_ms",
            "first_answer_ms",
            "time_to_results_ms",
            "retry_count",
            "request_count",
            "error_code",
            "error_fingerprint",
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
            "scope_hashes",
            "last_success_at",
            "last_attempt_id",
        }
    ),
    "attempt": frozenset(
        {
            "attempt_id",
            "connector_id",
            "cc_pair_id",
            "connector_type",
            "state",
            "docs_processed",
            "docs_indexed",
            "chunks_indexed",
            "total_batches",
            "completed_batches",
            "error_count",
            "error_code",
            "error_fingerprint",
            "fetch_docs",
            "embed_chunks",
            "write_chunks",
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
            "docs_total",
            "duration_ms",
            "error_count",
            "error_code",
            "error_fingerprint",
            "started_at",
            "ended_at",
            "entity_id",
            "cc_pair_id",
            "last_progress_at",
            "users_processed",
            "groups_processed",
            "memberships_synced",
        }
    ),
    "queue": frozenset(
        {
            "queue",
            "depth",
            "oldest_age_seconds",
            "in_flight",
            "enqueued",
            "dequeued",
            "retries",
            "drain_seconds",
            "shared",
        }
    ),
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
    "runtime": frozenset(
        {
            "service_instance_id",
            "reason",
            "restart_count",
            "restart_delta",
            "exit_code",
            "planned",
            "shared",
        }
    ),
    "version": frozenset({"version", "commit_sha", "image_digest", "shared"}),
    "heartbeat": frozenset(
        {
            "email_domain_errors",
            "stage_errors",
            "license_errors",
            "config_revision",
            "dropped_events",
            "recent_dropped_events",
            "rejected_events",
            "invalid_events",
            "spool_events",
            "connector_count",
            "collector_enabled",
            "source_errors",
            "source_consecutive_errors",
            "last_source_success_at",
            "queue_errors",
            "kubernetes_errors",
            "aws_errors",
            "aws_consecutive_errors",
            "last_aws_success_at",
            "schema_count",
        }
    ),
}
_ENUM_FIELDS: dict[str, frozenset[str]] = {
    "action": frozenset({"snapshot", "set", "removed"}),
    "state": _STATES,
    "connector_type": _SOURCES,
    "error_code": _ERRORS,
    "channel": frozenset({"web", "slack", "discord", "api"}),
    "mode": frozenset({"chat", "search"}),
    "outcome": frozenset(
        {"success", "failure", "partial", "canceled", "disconnected", "timeout"}
    ),
    "stage_name": frozenset(stage.value for stage in IndexAttemptStage),
    "opensearch_status": frozenset({"green", "yellow", "red", "unavailable"}),
    "queue": _QUEUES,
    "job_type": _JOB_TYPES,
    "counter_mode": frozenset({"snapshot", "delta"}),
    "stage": frozenset({"fetch", "prepare", "embed", "write"}),
    "reason": frozenset(
        {
            "started",
            "stopped",
            "oom",
            "evicted",
            "crash",
            "restart",
            "unready",
            "unknown",
        }
    ),
}


# Source-owned collection schedule. The fleet service cannot change it.
CONNECTOR_INTERVAL_SECONDS: int = 300
QUEUE_INTERVAL_SECONDS: int = 600
RESOURCE_INTERVAL_SECONDS: int = 300

# Delivery bounds. The fleet service accepts up to 500 events per request.
_MAX_BATCHES_PER_WAKEUP: int = 5
_MAX_EVENT_ATTEMPTS: int = 5
_FINAL_FLUSH_SECONDS: float = 5.0
# Short-lived processes wait at most this long at exit for their final delivery.
EXIT_FLUSH_SECONDS: float = 2.0
# Indexing counter deltas combine per attempt and stage for a short window.
_STAGE_WINDOW_SECONDS: float = 30.0
_MAX_STAGE_KEYS: int = 256


def is_valid_version(value: str) -> bool:
    """Accept only bounded release tags, build hashes, and fixed version labels."""
    return _VERSION.fullmatch(value) is not None


def normalize_email_domain(domain: str) -> str | None:
    if not domain or len(domain) > 253:
        return None
    try:
        domain = domain.encode("idna").decode("ascii").lower()
    except UnicodeError:
        return None
    return domain if len(domain) <= 253 and _EMAIL_DOMAIN.fullmatch(domain) else None


def sanitize_data(event_type: str, data: dict[str, Any]) -> dict[str, Any] | None:  # noqa: C901 - Central privacy boundary has explicit type cases.
    """Reject unknown fields and all unreviewed string values before queueing."""
    allowed: frozenset[str] | None = _FIELDS.get(event_type)
    if allowed is None or len(data) > 40 or not data.keys() <= allowed:
        return None
    safe: dict[str, Any] = {}
    for key, value in data.items():
        if value is None:
            safe[key] = None
        elif key in {"metadata", "counters"}:
            nested_allowed: frozenset[str] = (
                _METADATA if key == "metadata" else _COUNTERS
            )
            if (
                not isinstance(value, dict)
                or len(value) > len(nested_allowed)
                or not value.keys() <= nested_allowed
            ):
                return None
            safe[key] = {}
            for nested_key, nested_value in value.items():
                if nested_value is None:
                    safe[key][nested_key] = None
                elif (
                    type(nested_value) in {bool, int, float}
                    and math.isfinite(nested_value)
                    and 0 <= nested_value <= 1e18
                ):
                    safe[key][nested_key] = nested_value
                else:
                    return None
        elif key == "scope_hashes":
            if (
                not isinstance(value, list)
                or len(value) > 32
                or any(
                    not isinstance(item, str) or not _HEX.fullmatch(item)
                    for item in value
                )
            ):
                return None
            safe[key] = list(value)
        elif key == "domain":
            if not isinstance(value, str) or not (
                domain := normalize_email_domain(value)
            ):
                return None
            safe[key] = domain
        elif key in _ENUM_FIELDS:
            if not isinstance(value, str) or value not in _ENUM_FIELDS[key]:
                return None
            safe[key] = value
        elif key in {"config_hash", "error_fingerprint"}:
            if not isinstance(value, str) or not _HEX.fullmatch(value):
                return None
            safe[key] = value
        elif key in {"query_id", "job_id", "service_instance_id"}:
            if not isinstance(value, str) or not _OPAQUE.fullmatch(value):
                return None
            safe[key] = value
        elif key.endswith("_at"):
            if not isinstance(value, str) or len(value) > 40:
                return None
            try:
                parsed: datetime = datetime.fromisoformat(value)
                if parsed.tzinfo is None:
                    return None
            except ValueError:
                return None
            safe[key] = value
        elif key == "version":
            if not isinstance(value, str) or not is_valid_version(value):
                return None
            safe[key] = value
        elif key == "commit_sha":
            if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{7,40}", value):
                return None
            safe[key] = value
        elif key == "image_digest":
            if (
                not isinstance(value, str)
                or not value.startswith("sha256:")
                or not _HEX.fullmatch(value[7:])
            ):
                return None
            safe[key] = value
        elif (
            type(value) in {bool, int, float}
            and math.isfinite(value)
            and 0 <= value <= (1e30 if key == "m2_duration_ms" else 1e18)
        ):
            safe[key] = value
        else:
            return None
    return safe


def telemetry_disabled() -> bool:
    """Deployment-owned kill switch, shared with legacy callhome telemetry."""
    return os.environ.get("DISABLE_TELEMETRY", "").lower() == "true"


@dataclass(frozen=True)
class TelemetryConfig:
    endpoint: str
    token: str
    customer_uuid: str
    deployment_id: str
    privacy_key: bytes
    service: str = "api"
    capacity: int = 2048
    batch_size: int = 100
    flush_seconds: float = 2.0
    instance_domain_hash: str | None = None
    auto_enroll: bool = False

    @classmethod
    def from_env(
        cls, service: str, identity: dict[str, str] | None = None
    ) -> "TelemetryConfig | None":
        try:
            if telemetry_disabled():
                return None
            values: dict[str, str] = {**os.environ, **(identity or {})}
            endpoint: str = (
                values.get("ONYX_TELEMETRY_ENDPOINT") or "https://telemetry.onyx.app"
            ).rstrip("/")
            parsed: SplitResult = urlsplit(endpoint)
            if parsed.scheme != "https" and not (
                parsed.scheme == "http"
                and parsed.hostname in {"localhost", "127.0.0.1", "telemetry"}
            ):
                return None
            if (
                not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
            ):
                return None
            token: str = values["ONYX_TELEMETRY_TOKEN"]
            customer: str = str(uuid.UUID(values["ONYX_TELEMETRY_CUSTOMER_UUID"]))
            deployment: str = values["ONYX_TELEMETRY_DEPLOYMENT_ID"]
            privacy_key: bytes = values["ONYX_TELEMETRY_PRIVACY_KEY"].encode()
            if (
                not _OPAQUE.fullmatch(deployment)
                or len(privacy_key) < 32
                or not token
                or len(token) > 4096
            ):
                return None
            domain_hash: str | None = None
            domain: str | None = os.environ.get(
                "ONYX_TELEMETRY_INSTANCE_DOMAIN"
            ) or os.environ.get("WEB_DOMAIN")
            if domain and len(domain) <= 2048:
                try:
                    domain_parts: SplitResult = urlsplit(
                        domain if "://" in domain else "https://" + domain
                    )
                    if (
                        domain_parts.hostname
                        and not domain_parts.username
                        and not domain_parts.password
                    ):
                        host: str = (
                            domain_parts.hostname.rstrip(".")
                            .encode("idna")
                            .decode("ascii")
                            .lower()
                        )
                        if len(host) <= 253:
                            domain_hash = hmac.new(
                                privacy_key, host.encode(), hashlib.sha256
                            ).hexdigest()
                except (ValueError, UnicodeError):
                    pass
            return cls(
                endpoint,
                token,
                customer,
                deployment,
                privacy_key,
                service,
                instance_domain_hash=domain_hash,
                auto_enroll=identity is not None,
            )
        except (KeyError, ValueError):
            return None


class BoundedTelemetry:
    """One daemon thread per process. A full queue sheds events; emitters never wait."""

    def __init__(self, config: TelemetryConfig, *, report_process: bool = True) -> None:
        self.config: TelemetryConfig = config
        # Short-lived processes deliver hook events only; their parent reports the process.
        self.report_process: bool = report_process
        self.pid: int = os.getpid()
        # deque append/popleft are thread-safe, so emitters take no lock.
        self._queue: deque[
            tuple[
                str, dict[str, Any], str | None, str | None, float, str | None, str, int
            ]
        ] = deque()
        self._flush_lock: threading.Lock = threading.Lock()
        self._stop: threading.Event = threading.Event()
        self._thread: threading.Thread | None = None
        self.dropped: int = 0
        self.rejected: int = 0
        self.invalid: int = 0
        self._reported_dropped: int = 0
        self._recent_dropped: int = 0
        self._last_loss_at: float = float("-inf")
        self.sent: int = 0
        # Events dropped after the service deferred them `_MAX_EVENT_ATTEMPTS` times.
        self.expired: int = 0
        self.failures: int = 0
        self._blocked_until: float = 0.0
        self._pending: list[dict[str, Any]] = []
        # Sends per retained event ID. Whole-request failures do not count.
        self._attempts: dict[str, int] = {}
        self._session: requests.Session | None = None
        self._enrolled: bool = not config.auto_enroll
        self._stage_pending: OrderedDict[tuple[str, ...], dict[str, Any]] = (
            OrderedDict()
        )
        self._last_stage_flush: float = time.monotonic()
        self.health: dict[str, Any] = {}

    def emit(
        self,
        event_type: str,
        data: dict[str, Any],
        *,
        user_id: str | None = None,
        tenant_id: str | None = None,
        event_id: str | None = None,
        occurred_at: float | None = None,
        service: str | None = None,
        revision: int = 0,
    ) -> bool:
        """No locks, thread creation, serialization, logging, network, disk, or database calls."""
        try:
            if (
                self.pid != os.getpid()
                or self._stop.is_set()
                or (service is not None and service not in _SERVICES)
                or type(revision) is not int
                or not 0 <= revision <= 1_000_000_000
            ):
                return False
            safe: dict[str, Any] | None = sanitize_data(event_type, data)
            if safe is None:
                self.invalid += 1
                self.dropped += 1
                return False
            # Concurrent emitters can overshoot the capacity by at most one event each.
            if len(self._queue) >= self.config.capacity:
                self.dropped += 1
                return False
            # Only UUID user identifiers are transmitted. Never send email or bot names.
            if user_id is not None:
                try:
                    user_id = str(uuid.UUID(user_id)) if len(user_id) == 36 else None
                except ValueError:
                    user_id = None
            self._queue.append(
                (
                    event_type,
                    safe,
                    user_id,
                    tenant_id,
                    occurred_at if occurred_at is not None else time.time(),
                    event_id,
                    service or self.config.service,
                    revision,
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

    def fingerprint(self, value: str) -> str:
        return hmac.new(
            self.config.privacy_key, value.encode(), hashlib.sha256
        ).hexdigest()

    def _take_batch(self, limit: int | None = None) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for _ in range(self.config.batch_size if limit is None else limit):
            try:
                (
                    event_type,
                    data,
                    user_id,
                    tenant,
                    occurred_at,
                    event_id,
                    service,
                    revision,
                ) = self._queue.popleft()
            except IndexError:
                break
            try:
                events.append(
                    self._envelope(
                        event_type,
                        data,
                        user_id,
                        tenant,
                        occurred_at,
                        event_id,
                        service,
                        revision,
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
        user_id: str | None,
        tenant: str | None,
        occurred_at: float,
        event_id: str | None,
        service: str,
        revision: int,
    ) -> dict[str, Any]:
        customer: str = (
            str(uuid.uuid5(uuid.NAMESPACE_X500, tenant))
            if MULTI_TENANT and tenant
            else self.config.customer_uuid
        )
        scope: str | None = (
            customer if MULTI_TENANT and tenant and self.config.auto_enroll else None
        )
        if scope:
            customer = str(uuid.uuid5(uuid.UUID(self.config.customer_uuid), scope))
        return {
            "schema_version": 2,
            "revision": revision,
            "event_id": event_id or str(uuid.uuid4()),
            "event_type": event_type,
            "occurred_at": datetime.fromtimestamp(
                occurred_at, timezone.utc
            ).isoformat(),
            "customer_uuid": customer,
            "deployment_id": self.config.deployment_id,
            **({"installation_scope": scope} if scope else {}),
            "service": service,
            "user_id": user_id,
            "is_cloud": MULTI_TENANT,
            **(
                {"instance_domain": self.config.instance_domain_hash}
                if self.config.instance_domain_hash
                else {}
            ),
            "data": data,
        }

    def flush_once(self, transport: Any = None) -> bool:
        """Send one batch. True when it was fully delivered or nothing was due.

        Retained events keep stable IDs across retries.
        """
        if not self._flush_lock.acquire(blocking=False):
            return False
        try:
            return self._flush_once(transport)
        finally:
            self._flush_lock.release()

    def _flush_once(self, transport: Any = None) -> bool:
        if time.monotonic() < self._blocked_until:
            return False
        room: int = self.config.batch_size - len(self._pending)
        if room > 0:
            self._pending.extend(self._coalesce_stages(self._take_batch(room), room))
        if not self._pending:
            return True
        try:
            if transport is None:
                if self._session is None:
                    self._session = requests.Session()
                transport = self._session.post
            self._enroll(transport)
            response: requests.Response = transport(
                self.config.endpoint + "/v1/events",
                headers={
                    "Authorization": "Bearer " + self.config.token,
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
                if response.headers.get("Content-Encoding", "identity") not in {
                    "",
                    "identity",
                }:
                    raise ValueError("Unsupported telemetry response encoding")
                if not response.ok:
                    self._enrolled = self._enrolled and not (
                        response.status_code == 401 and self.config.auto_enroll
                    )
                    if response.status_code in {400, 413, 422}:
                        self.rejected += len(self._pending)
                        self.dropped += len(self._pending)
                        self._pending = []
                        self._attempts = {}
                    raise RuntimeError("telemetry delivery failed")
                raw: bytes = response.raw.read(65537)
                if len(raw) > 65536:
                    raise ValueError("Telemetry response exceeds limit")
                result: Any = json.loads(raw)
        except Exception:
            # Outages keep the batch and back off; nothing counts against its events.
            self.failures = min(self.failures + 1, 8)
            self._blocked_until = time.monotonic() + min(300, 2**self.failures)
            return False
        self.failures = 0
        outcomes: dict[int, str] = {}
        if isinstance(result, dict) and isinstance(result.get("results"), list):
            for item in result["results"][: len(self._pending)]:
                if isinstance(item, dict) and type(item.get("index")) is int:
                    index: int = item["index"]
                    if 0 <= index < len(self._pending) and item.get("status") in {
                        "accepted",
                        "rejected",
                        "retry",
                    }:
                        if item.get("event_id") not in {
                            None,
                            self._pending[index]["event_id"],
                        }:
                            continue
                        outcomes[index] = item["status"]
        retained: list[dict[str, Any]] = []
        attempts: dict[str, int] = {}
        for index, event in enumerate(self._pending):
            outcome: str | None = outcomes.get(index)
            if outcome == "accepted":
                self.sent += 1
            elif outcome == "rejected":
                self.rejected += 1
                self.dropped += 1
            else:
                event_id: str = event["event_id"]
                count: int = self._attempts.get(event_id, 0) + 1
                # Events the service keeps deferring must not hold back newer events.
                if count >= _MAX_EVENT_ATTEMPTS:
                    self.expired += 1
                    self.dropped += 1
                else:
                    attempts[event_id] = count
                    retained.append(event)
        self._pending = retained
        self._attempts = attempts
        return not retained

    def _enroll(self, transport: Any) -> None:
        if self._enrolled:
            return
        response: requests.Response = transport(
            self.config.endpoint + "/v1/enroll",
            headers={
                "Authorization": "Bearer " + self.config.token,
                "Accept-Encoding": "identity",
            },
            json={"is_cloud": MULTI_TENANT},
            timeout=(1, 2),
            allow_redirects=False,
            stream=True,
        )
        with response:
            if response.status_code != 200 or response.headers.get(
                "Content-Encoding", "identity"
            ) not in {"", "identity"}:
                raise ValueError("Fleet enrollment unavailable")
            raw: bytes = response.raw.read(4097)
            if len(raw) > 4096:
                raise ValueError("Fleet enrollment receipt too large")
            result: object = json.loads(raw)
            if (
                not isinstance(result, dict)
                or result.get("customer_uuid") != self.config.customer_uuid
                or result.get("deployment_id") != self.config.deployment_id
            ):
                raise ValueError("Fleet enrollment identity mismatch")
        self._enrolled = True

    def _coalesce_stages(
        self, events: list[dict[str, Any]], limit: int
    ) -> list[dict[str, Any]]:
        """Combine batch counters in the sender thread; errors bypass the short window."""
        ready: list[dict[str, Any]] = []
        for event in events:
            data: dict[str, Any] = event["data"]
            if (
                event["event_type"] != "attempt"
                or data.get("counter_mode") != "delta"
                or "attempt_id" not in data
            ):
                ready.append(event)
                continue
            key: tuple[str, ...] = (
                event["customer_uuid"],
                event["service"],
                str(data["attempt_id"]),
                str(data.get("stage", "unknown")),
            )
            previous: dict[str, Any] | None = self._stage_pending.pop(key, None)
            if previous:
                old: dict[str, Any] = previous["data"]
                counters: dict[str, int | float] = dict(old.get("counters") or {})
                for name, value in (data.get("counters") or {}).items():
                    if value is not None:
                        counters[name] = (counters.get(name) or 0) + value
                data["counters"] = counters
                for name in (
                    "duration_ms",
                    "fetch_docs",
                    "embed_chunks",
                    "write_docs",
                    "write_chunks",
                    "write_errors",
                    "write_rejected",
                    "error_count",
                ):
                    if old.get(name) is not None:
                        data[name] = (data.get(name) or 0) + old[name]
            if any(
                data.get(name) or (data.get("counters") or {}).get(name)
                for name in (
                    "error_count",
                    "fetch_errors",
                    "embed_errors",
                    "write_errors",
                    "write_rejected",
                )
            ):
                ready.append(event)
            else:
                self._stage_pending[key] = event
            if len(self._stage_pending) > _MAX_STAGE_KEYS:
                ready.append(self._stage_pending.popitem(last=False)[1])
        # A closed sender has no later window, so it releases every counter now.
        if (
            self._stop.is_set()
            or time.monotonic() - self._last_stage_flush >= _STAGE_WINDOW_SECONDS
        ):
            while self._stage_pending and len(ready) < limit:
                ready.append(self._stage_pending.popitem(last=False)[1])
            if not self._stage_pending:
                self._last_stage_flush = time.monotonic()
        return ready

    def delivery_health(self) -> dict[str, int]:
        """Background observations distinguish new loss from historical totals."""
        dropped: int = self.dropped
        now: float = time.monotonic()
        if now - self._last_loss_at >= 60:
            self._recent_dropped = 0
        delta: int = max(0, dropped - self._reported_dropped)
        if delta:
            self._recent_dropped += delta
            self._last_loss_at = now
        self._reported_dropped = dropped
        return {
            "dropped_events": dropped,
            "recent_dropped_events": self._recent_dropped,
            "rejected_events": self.rejected,
            "invalid_events": self.invalid,
            "spool_events": len(self._queue)
            + len(self._pending)
            + len(self._stage_pending),
        }

    def _report_start(self) -> None:
        self.emit(
            "runtime",
            {
                "service_instance_id": self.fingerprint(
                    str(os.getpid()) + ":" + str(time.time_ns())
                ),
                "reason": "started",
                "restart_count": 0,
            },
        )
        from onyx import __version__

        version: str = "dev" if __version__ == "Development" else __version__
        version_data: dict[str, Any] = {
            "version": version if is_valid_version(version) else "unknown"
        }
        commit_sha: str = os.environ.get("ONYX_BUILD_SHA", "")
        if re.fullmatch(r"[a-f0-9]{7,40}", commit_sha):
            version_data["commit_sha"] = commit_sha
        self.emit("version", version_data)

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
                        if (
                            not self.flush_once()
                            or len(self._queue) < self.config.batch_size
                        ):
                            break
                except Exception:
                    # One failed iteration never ends delivery for the process.
                    pass
                self._stop.wait(self.config.flush_seconds)
            self._final_flush()
        except Exception:
            # Telemetry failure never reaches the application, including initialization.
            pass
        finally:
            if self._session is not None:
                self._session.close()

    def _final_flush(self) -> None:
        """Release coalesced counters and send what remains while delivery is healthy.

        Short-lived processes (e.g. spawned indexing children) otherwise exit with
        their final counters still inside the coalescing window. A failed or
        backed-off delivery ends the attempt immediately.
        """
        deadline: float = time.monotonic() + _FINAL_FLUSH_SECONDS
        while (
            self._queue or self._pending or self._stage_pending
        ) and time.monotonic() < deadline:
            if not self.flush_once():
                return


def poll_due(previous: float | None, now: float, interval: float) -> bool:
    """Poll immediately before the first attempt, regardless of host uptime."""
    return previous is None or now - previous >= interval


_client: BoundedTelemetry | None = None
_bootstrap_lock: threading.Lock = threading.Lock()
_bootstrap_thread: threading.Thread | None = None
_bootstrap_stop: threading.Event = threading.Event()
_bootstrap_pid: int = 0


def automatic_config(service: str, seed: bytes) -> TelemetryConfig | None:
    token: str = hmac.new(seed, b"fleet-enrollment-v1", hashlib.sha256).hexdigest()
    namespace: uuid.UUID = uuid.uuid5(
        uuid.NAMESPACE_URL,
        "https://telemetry.onyx.app/installations/"
        + hashlib.sha256(token.encode()).hexdigest(),
    )
    return TelemetryConfig.from_env(
        service,
        {
            "ONYX_TELEMETRY_TOKEN": token,
            "ONYX_TELEMETRY_CUSTOMER_UUID": str(namespace),
            "ONYX_TELEMETRY_DEPLOYMENT_ID": "auto-" + namespace.hex,
            "ONYX_TELEMETRY_PRIVACY_KEY": hmac.new(
                seed, b"fleet-privacy-v1", hashlib.sha256
            ).hexdigest(),
        },
    )


def _bootstrap(service: str, report_process: bool, stopped: threading.Event) -> None:
    global _client
    delay: float = 2.0
    edition_wait: float = 0.1
    while not stopped.is_set() and not telemetry_disabled():
        try:
            from onyx.db.fleet_enrollment import edition_selected, installation_seed

            if not edition_selected():
                # A local check: spawned children select their edition right after start.
                stopped.wait(edition_wait)
                edition_wait = min(5.0, edition_wait * 2)
                continue
            config: TelemetryConfig | None = automatic_config(
                service, installation_seed()
            )
            if config is None or stopped.is_set() or telemetry_disabled():
                return
            client: BoundedTelemetry = BoundedTelemetry(
                config, report_process=report_process
            )
            _client = client
            client.start()
            return
        except Exception:
            # No source/network error reaches application startup. No raw logs.
            stopped.wait(delay)
            delay = min(300, delay * 2)


def start_telemetry(
    service: str = "api", *, report_process: bool = True
) -> BoundedTelemetry | None:
    """Start this process's sender in the background; never waits for identity or I/O.

    `report_process=False` suits short-lived processes: they deliver hook events
    without startup, resource, or heartbeat reports of their own.
    """
    global _client, _bootstrap_thread, _bootstrap_stop, _bootstrap_pid
    if telemetry_disabled():
        return None
    try:
        if _client is not None and _client.pid == os.getpid() and not _client.closed:
            return _client
        config: TelemetryConfig | None = TelemetryConfig.from_env(service)
        if config is None:
            # Partial explicit credentials fail closed instead of creating a new identity.
            if any(
                os.environ.get("ONYX_TELEMETRY_" + key)
                for key in ("TOKEN", "CUSTOMER_UUID", "DEPLOYMENT_ID", "PRIVACY_KEY")
            ):
                return None
            if not _bootstrap_lock.acquire(blocking=False):
                return None
            try:
                if (
                    _bootstrap_pid != os.getpid()
                    or _bootstrap_thread is None
                    or not _bootstrap_thread.is_alive()
                ):
                    _bootstrap_stop = threading.Event()
                    _bootstrap_pid = os.getpid()
                    _bootstrap_thread = threading.Thread(
                        target=_bootstrap,
                        args=(service, report_process, _bootstrap_stop),
                        name="fleet-telemetry-enrollment",
                        daemon=True,
                    )
                    _bootstrap_thread.start()
            finally:
                _bootstrap_lock.release()
            return None
        _client = BoundedTelemetry(config, report_process=report_process)
        _client.start()
        return _client
    except Exception:
        return None


def stop_telemetry(flush_timeout: float = 0.0) -> None:
    """Stop enrollment and sending. Waits at most `flush_timeout` for a final delivery."""
    _bootstrap_stop.set()
    if _client is not None:
        _client.close(flush_timeout)


def emit_telemetry(
    event_type: str,
    data: dict[str, Any],
    *,
    user_id: str | None = None,
    tenant_id: str | None = None,
) -> bool:
    try:
        if _client is None:
            return False
        return _client.emit(
            event_type,
            data,
            user_id=user_id,
            tenant_id=tenant_id or get_current_tenant_id(),
        )
    except Exception:
        return False


def emit_signup_domain(email: str, created_at: datetime) -> None:
    try:
        if _client is None or len(email) > 320 or email.count("@") != 1:
            return
        domain: str | None = normalize_email_domain(email.partition("@")[2])
        if domain and created_at.tzinfo is not None:
            emit_telemetry(
                "tenant_domain",
                {"domain": domain, "first_signup_at": created_at.isoformat()},
            )
    except Exception:
        return


def emit_license_state(
    present: bool, action: str, first_set_at: datetime | None = None
) -> None:
    try:
        emit_telemetry(
            "license",
            {
                "license_present": present,
                "action": action,
                "first_set_at": first_set_at.isoformat() if first_set_at else None,
            },
        )
    except Exception:
        return


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
    if name in {"AuthenticationError", "ConnectorAuthError", "AuthError"}:
        return "auth"
    if name in {"PermissionError", "PermissionDeniedError"}:
        return "permission"
    if name in {"RateLimitError", "RateLimitException"}:
        return "rate_limit"
    if name in {"BulkIndexError", "OpenSearchIndexError", "TransportError"}:
        return "index_write"
    if name in {"ConnectionError", "APIConnectionError", "ConnectionTimeout"}:
        return "source_unavailable"
    return "internal"
