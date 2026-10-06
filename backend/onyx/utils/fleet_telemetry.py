"""Bounded, lossy fleet telemetry. Application threads never perform telemetry I/O."""

import hashlib
import hmac
import json
import math
import os
import re
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

from onyx.configs.constants import DocumentSource, OnyxCeleryQueues
from shared_configs.configs import MULTI_TENANT
from shared_configs.contextvars import get_current_tenant_id

_HEX = re.compile(r"[a-f0-9]{64}\Z")
_EMAIL_DOMAIN = re.compile(
    r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?\Z"
)
_OPAQUE = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")
_VERSION = re.compile(
    r"(?:v?\d{1,4}\.\d{1,4}(?:\.\d{1,4})?(?:[-.](?:cloud|beta|alpha|rc|dev|nightly|release)(?:[-.]?\d{1,8})?){0,3}|[a-f0-9]{7,40}|unknown|dev|nightly)\Z"
)
_STATES = frozenset(
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
_ERRORS = frozenset(
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
_SOURCES = frozenset(source.value for source in DocumentSource)
_QUEUES = frozenset(
    value
    for key, value in vars(OnyxCeleryQueues).items()
    if not key.startswith("_") and isinstance(value, str)
)
_JOB_TYPES = frozenset(
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
_SERVICES = frozenset(
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
_METADATA = frozenset(
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
_COUNTERS = frozenset(
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
_ENUM_FIELDS = {
    "state": _STATES,
    "connector_type": _SOURCES,
    "error_code": _ERRORS,
    "channel": frozenset({"web", "slack", "discord", "api"}),
    "mode": frozenset({"chat", "search"}),
    "outcome": frozenset(
        {"success", "failure", "partial", "canceled", "disconnected", "timeout"}
    ),
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
    allowed = _FIELDS.get(event_type)
    if allowed is None or len(data) > 40 or not data.keys() <= allowed:
        return None
    safe: dict[str, Any] = {}
    for key, value in data.items():
        if value is None:
            safe[key] = None
        elif key in {"metadata", "counters"}:
            nested_allowed = _METADATA if key == "metadata" else _COUNTERS
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
                parsed = datetime.fromisoformat(value)
                if parsed.tzinfo is None:
                    return None
            except ValueError:
                return None
            safe[key] = value
        elif key == "version":
            if not isinstance(value, str) or not _VERSION.fullmatch(value):
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
            and 0 <= value <= 1e18
        ):
            safe[key] = value
        else:
            return None
    return safe


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

    @classmethod
    def from_env(cls, service: str) -> "TelemetryConfig | None":
        try:
            if os.environ.get("DISABLE_TELEMETRY", "").lower() == "true":
                return None
            endpoint = os.environ["ONYX_TELEMETRY_ENDPOINT"].rstrip("/")
            parsed = urlsplit(endpoint)
            if parsed.scheme != "https" and not (
                parsed.scheme == "http"
                and parsed.hostname in {"localhost", "127.0.0.1", "telemetry"}
            ):
                return None
            if parsed.username or parsed.password or parsed.query or parsed.fragment:
                return None
            token = os.environ["ONYX_TELEMETRY_TOKEN"]
            customer = str(uuid.UUID(os.environ["ONYX_TELEMETRY_CUSTOMER_UUID"]))
            deployment = os.environ["ONYX_TELEMETRY_DEPLOYMENT_ID"]
            privacy_key = os.environ["ONYX_TELEMETRY_PRIVACY_KEY"].encode()
            if (
                not _OPAQUE.fullmatch(deployment)
                or len(privacy_key) < 32
                or len(token) > 4096
            ):
                return None
            domain_hash: str | None = None
            domain = os.environ.get("ONYX_TELEMETRY_INSTANCE_DOMAIN") or os.environ.get(
                "WEB_DOMAIN"
            )
            if domain and len(domain) <= 2048:
                try:
                    domain_parts = urlsplit(
                        domain if "://" in domain else "https://" + domain
                    )
                    if (
                        domain_parts.hostname
                        and not domain_parts.username
                        and not domain_parts.password
                    ):
                        host = (
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
            )
        except (KeyError, ValueError):
            return None


class BoundedTelemetry:
    """One daemon thread per process. Full queues and lock contention shed events."""

    def __init__(self, config: TelemetryConfig) -> None:
        self.config = config
        self.pid = os.getpid()
        self._queue: deque[
            tuple[
                str, dict[str, Any], str | None, str | None, float, str | None, str, int
            ]
        ] = deque()
        self._lock = threading.Lock()
        self._flush_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.dropped = 0
        self.rejected = 0
        self.invalid = 0
        self._reported_dropped = 0
        self._recent_dropped = 0
        self._last_loss_at = float("-inf")
        self.sent = 0
        self.failures = 0
        self._blocked_until = 0.0
        self._pending: list[dict[str, Any]] = []
        self.health: dict[str, Any] = {}
        self.settings: dict[str, Any] = {
            "config_revision": 0,
            "enabled": True,
            "connector_interval_seconds": 300,
            "queue_interval_seconds": 600,
            "resource_interval_seconds": 300,
        }

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
        """No thread creation, serialization, logging, network, disk, or database calls."""
        try:
            if (
                self.pid != os.getpid()
                or self._stop.is_set()
                or not self.settings["enabled"]
                or (service is not None and service not in _SERVICES)
                or type(revision) is not int
                or not 0 <= revision <= 1_000_000_000
            ):
                return False
            safe = sanitize_data(event_type, data)
            if safe is None:
                self.invalid += 1
                self.dropped += 1
                return False
            if not self._lock.acquire(blocking=False):
                self.dropped += 1
                return False
            try:
                if len(self._queue) >= self.config.capacity:
                    self.dropped += 1
                    return False
                # Only UUID user identifiers are transmitted. Never send email or bot names.
                if user_id is not None:
                    try:
                        user_id = (
                            str(uuid.UUID(user_id)) if len(user_id) == 36 else None
                        )
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
            finally:
                self._lock.release()
        except Exception:
            self.dropped += 1
            return False

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run, name="fleet-telemetry-sender", daemon=True
        )
        self._thread.start()

    def close(self) -> None:
        # Shutdown must not wait on DNS, TLS, transport, or collectors.
        self._stop.set()

    def fingerprint(self, value: str) -> str:
        return hmac.new(
            self.config.privacy_key, value.encode(), hashlib.sha256
        ).hexdigest()

    def _take_batch(self) -> list[dict[str, Any]]:
        with self._lock:
            items = [
                self._queue.popleft()
                for _ in range(min(len(self._queue), self.config.batch_size))
            ]
        events = []
        for (
            event_type,
            data,
            user_id,
            tenant,
            occurred_at,
            event_id,
            service,
            revision,
        ) in items:
            customer = (
                str(uuid.uuid5(uuid.NAMESPACE_X500, tenant))
                if MULTI_TENANT and tenant
                else self.config.customer_uuid
            )
            events.append(
                {
                    "schema_version": 2,
                    "revision": revision,
                    "event_id": event_id or str(uuid.uuid4()),
                    "event_type": event_type,
                    "occurred_at": datetime.fromtimestamp(
                        occurred_at, timezone.utc
                    ).isoformat(),
                    "customer_uuid": customer,
                    "deployment_id": self.config.deployment_id,
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
            )
        return events

    def flush_once(self, transport: Any = None) -> bool:
        """Worker/test entry only. A retained batch has stable IDs across retries."""
        if not self._flush_lock.acquire(blocking=False):
            return False
        try:
            return self._flush_once(transport)
        finally:
            self._flush_lock.release()

    def _flush_once(self, transport: Any = None) -> bool:
        if time.monotonic() < self._blocked_until:
            return False
        if not self._pending:
            self._pending = self._take_batch()
        if not self._pending:
            return True
        try:
            if transport is None:
                import requests

                transport = requests.post
            response = transport(
                self.config.endpoint + "/v1/events",
                headers={
                    "Authorization": "Bearer " + self.config.token,
                    "Content-Type": "application/json",
                    "Accept-Encoding": "identity",
                },
                data=json.dumps({"events": self._pending}, separators=(",", ":")),
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
                    if response.status_code in {400, 413, 422}:
                        self.rejected += len(self._pending)
                        self.dropped += len(self._pending)
                        self._pending = []
                    raise RuntimeError("telemetry delivery failed")
                raw = response.raw.read(65537)
                if len(raw) > 65536:
                    raise ValueError("Telemetry response exceeds limit")
                result = json.loads(raw)
            outcomes: dict[int, str] = {}
            if isinstance(result, dict) and isinstance(result.get("results"), list):
                for item in result["results"][: self.config.batch_size]:
                    if isinstance(item, dict) and type(item.get("index")) is int:
                        index = item["index"]
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
            retained = []
            for index, event in enumerate(self._pending):
                outcome = outcomes.get(index)
                if outcome == "accepted":
                    self.sent += 1
                elif outcome == "rejected":
                    self.rejected += 1
                    self.dropped += 1
                else:
                    retained.append(event)
            self._pending = retained
            if self._pending:
                raise RuntimeError("Partial telemetry delivery; retry retained IDs")
            self.failures = 0
            return True
        except Exception:
            self.failures = min(self.failures + 1, 8)
            self._blocked_until = time.monotonic() + min(300, 2**self.failures)
            return False

    def _poll_settings(self) -> None:
        try:
            import requests

            response = requests.get(
                self.config.endpoint + "/v1/config",
                headers={
                    "Authorization": "Bearer " + self.config.token,
                    "Accept-Encoding": "identity",
                },
                params={
                    "deployment_id": self.config.deployment_id,
                    "customer_uuid": self.config.customer_uuid,
                },
                timeout=(1, 2),
                allow_redirects=False,
                stream=True,
            )
            with response:
                if not response.ok or response.headers.get(
                    "Content-Encoding", "identity"
                ) not in {"", "identity"}:
                    return
                body = response.raw.read(8193)
                if len(body) > 8192:
                    return
                remote = json.loads(body)
            if not isinstance(remote, dict):
                return
            settings = dict(self.settings)
            for key in {
                "connector_interval_seconds",
                "queue_interval_seconds",
                "resource_interval_seconds",
            }:
                value = remote.get(key)
                if type(value) is int and 60 <= value <= 3600:
                    settings[key] = value
            if type(remote.get("config_revision")) is int:
                settings["config_revision"] = max(0, remote["config_revision"])
            if type(remote.get("enabled")) is bool:
                settings["enabled"] = remote["enabled"]
            self.settings = settings
        except Exception:
            pass

    def delivery_health(self) -> dict[str, int]:
        """Background observations distinguish new loss from historical totals."""
        dropped = self.dropped
        now = time.monotonic()
        if now - self._last_loss_at >= 60:
            self._recent_dropped = 0
        delta = max(0, dropped - self._reported_dropped)
        if delta:
            self._recent_dropped += delta
            self._last_loss_at = now
        self._reported_dropped = dropped
        return {
            "dropped_events": dropped,
            "recent_dropped_events": self._recent_dropped,
            "rejected_events": self.rejected,
            "invalid_events": self.invalid,
            "spool_events": len(self._queue) + len(self._pending),
        }

    def _run(self) -> None:
        last_resource: float | None = None
        last_config: float | None = None
        try:
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

            version = "dev" if __version__ == "Development" else __version__
            version_data = {
                "version": version if _VERSION.fullmatch(version) else "unknown"
            }
            commit_sha = os.environ.get("ONYX_BUILD_SHA", "")
            if re.fullmatch(r"[a-f0-9]{7,40}", commit_sha):
                version_data["commit_sha"] = commit_sha
            self.emit("version", version_data)
            while not self._stop.is_set():
                now = time.monotonic()
                if poll_due(last_config, now, 60):
                    self._poll_settings()
                    last_config = now
                if self.settings["enabled"] and poll_due(
                    last_resource, now, self.settings["resource_interval_seconds"]
                ):
                    from onyx.utils.fleet_telemetry_resources import (
                        collect_process_resource,
                    )

                    collect_process_resource(self)
                    self.emit(
                        "heartbeat",
                        {
                            "config_revision": self.settings["config_revision"],
                            **self.delivery_health(),
                            "collector_enabled": True,
                            **self.health,
                        },
                    )
                    last_resource = now
                self.flush_once()
                self._stop.wait(self.config.flush_seconds)
        except Exception:
            # Telemetry failure never reaches the application, including initialization.
            pass


def poll_due(previous: float | None, now: float, interval: float) -> bool:
    """Poll immediately before the first attempt, regardless of host uptime."""
    return previous is None or now - previous >= interval


_client: BoundedTelemetry | None = None


def start_telemetry(service: str = "api") -> BoundedTelemetry | None:
    global _client
    try:
        if (
            _client is not None
            and _client.pid == os.getpid()
            and not _client._stop.is_set()
        ):
            return _client
        config = TelemetryConfig.from_env(service)
        if config is None:
            return None
        _client = BoundedTelemetry(config)
        _client.start()
        return _client
    except Exception:
        return None


def stop_telemetry() -> None:
    if _client is not None:
        _client.close()


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
        domain = normalize_email_domain(email.partition("@")[2])
        if domain and created_at.tzinfo is not None:
            emit_telemetry(
                "tenant_domain",
                {"domain": domain, "first_signup_at": created_at.isoformat()},
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
    name = type(error).__name__
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
