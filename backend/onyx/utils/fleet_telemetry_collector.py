"""Isolated collector: python -m onyx.utils.fleet_telemetry_collector.

No collector queries run inside an API request or indexing task. Use a read-only
source database role and container resource limits. Source failures only drop
telemetry; bounded reads never hold source transactions open between polls.
"""

import argparse
import hashlib
import json
import os
import re
import signal
import threading
import time
import uuid
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from onyx.db.fleet_enrollment import source_database_url
from onyx.db.fleet_telemetry import (
    SAFE_BOOLEAN_SETTINGS,
    SAFE_NUMBER_SETTINGS,
    attempt_page,
    collector_engine,
    connector_page,
    email_domain_page,
    job_page,
    license_snapshot,
    stage_metric_page,
    tenant_schemas,
)
from onyx.utils.fleet_telemetry import (
    CONNECTOR_INTERVAL_SECONDS,
    EXIT_FLUSH_SECONDS,
    QUEUE_INTERVAL_SECONDS,
    RESOURCE_INTERVAL_SECONDS,
    BoundedTelemetry,
    normalize_email_domain,
    poll_due,
    start_telemetry,
    stop_telemetry,
    telemetry_disabled,
)
from onyx.utils.variable_functionality import set_is_ee_if_available
from shared_configs.configs import MULTI_TENANT

SOURCE_EVENT_REVISION: int = 1
# Attempt and job history stays inside the service's 190-day horizon.
_HISTORY_HORIZON: timedelta = timedelta(days=184)
# Stage summaries stay inside the service's 30-day diagnostics horizon.
_STAGE_HORIZON: timedelta = timedelta(days=29)
# At the live edge, the next read re-covers a short overlap for rows that commit late.
_REPAIR_OVERLAP: timedelta = timedelta(minutes=10)
# A wider sweep resends recent rows every six hours and after deferred events expire.
_REPAIR_WINDOW: timedelta = timedelta(hours=24)
_REPAIR_INTERVAL_SECONDS: int = 6 * 3600


def _iso(value: Any) -> str | None:
    if isinstance(value, datetime):
        return (
            value.replace(tzinfo=timezone.utc).isoformat()
            if value.tzinfo is None
            else value.isoformat()
        )
    return None


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


def classify_local_error(*samples: Any) -> str:
    """Examine bounded local samples; emit only a fixed category, never text."""
    candidate: str = " ".join(
        sample[:2048] for sample in samples if isinstance(sample, str)
    )[:6144]
    for category, pattern in _ERROR_PATTERNS:
        if re.search(pattern, candidate, re.IGNORECASE):
            return category
    return "internal"


def safe_attempt_error_data(
    row: dict[str, Any], client: BoundedTelemetry
) -> dict[str, Any]:
    category: str = classify_local_error(
        row.get("local_error_type"),
        row.get("local_error_sample"),
        row.get("local_item_error_sample"),
    )
    data: dict[str, Any] = {
        "error_count": max(row["error_count"] or 0, int(row["has_error"])),
        "error_code": category,
        "error_fingerprint": client.fingerprint(
            "attempt:" + str(row["connector_type"]) + ":" + category
        ),
    }
    stage: str | None = {
        "embedding": "embed",
        "index_write": "write",
        "parse": "prepare",
    }.get(category)
    if stage is not None:
        data["stage"] = stage
    return data


def safe_connector_data(
    row: dict[str, Any], client: BoundedTelemetry
) -> dict[str, Any]:
    raw: Any = row.get("metadata", {})
    allowed: set[str] = set(SAFE_BOOLEAN_SETTINGS + SAFE_NUMBER_SETTINGS) | {
        "selection_count",
        "include_rule_count",
        "exclude_rule_count",
        "include_pattern_count",
        "exclude_pattern_count",
        "file_type_count",
        "has_time_filter",
    }
    metadata: dict[str, bool | int | float] = (
        {
            key: value
            for key, value in raw.items()
            if key in allowed
            and type(value) in {bool, int, float}
            and 0 <= value <= 1e18
        }
        if isinstance(raw, dict)
        else {}
    )
    for key in {
        "refresh_seconds",
        "prune_seconds",
        "auto_sync_enabled",
        "permission_sync_enabled",
    }:
        value: object = row.get(key)
        if isinstance(value, (bool, int, float)) and 0 <= value <= 1e18:
            metadata[key] = value
    return {
        "connector_id": row["connector_id"],
        "cc_pair_id": row["cc_pair_id"],
        "connector_type": row["connector_type"].lower(),
        "state": row["state"],
        "doc_count": row.get("doc_count") or 0,
        "last_success_at": _iso(row.get("last_success_at")),
        "config_hash": client.fingerprint(
            json.dumps(metadata, sort_keys=True, separators=(",", ":"))
        ),
        "metadata": metadata,
    }


class FleetCollector:
    def __init__(
        self, client: BoundedTelemetry, database_url: str, schemas: list[str]
    ) -> None:
        self.client: BoundedTelemetry = client
        self.engine: Engine = collector_engine(database_url)
        self.schemas: list[str] = schemas
        self.shard_count: int = max(
            1, min(1000, int(os.environ.get("ONYX_TELEMETRY_SCHEMA_SHARD_COUNT", "1")))
        )
        self.shard_index: int = int(
            os.environ.get("ONYX_TELEMETRY_SCHEMA_SHARD_INDEX", "0")
        )
        if not 0 <= self.shard_index < self.shard_count:
            raise ValueError("Invalid collector shard")
        self.schemas = self._partition(schemas)
        self._last_discovery: float | None = None
        self._discover: bool = (
            MULTI_TENANT and "ONYX_TELEMETRY_SCHEMAS" not in os.environ
        )
        self._failed_schema: dict[str, tuple[float, int]] = {}
        self._connector_cursor: dict[str, int] = {}
        self._last_connectors: dict[str, float] = {}
        self._domain_cursor: dict[str, str] = {}
        self._last_domains: dict[str, float] = {}
        self.email_domain_errors: int = 0
        self.license_errors: int = 0
        self._last_license: dict[str, float] = {}
        self._stage_cursor: dict[str, tuple[datetime, int]] = {}
        self._last_stages: dict[str, float] = {}
        self.stage_errors: int = 0
        self._last_opensearch: float | None = None
        self._attempt_cursor: dict[str, tuple[datetime, int]] = {}
        self._job_cursor: dict[str, tuple[datetime, str]] = {}
        self._active_job_cursor: dict[str, str] = {}
        self._last_attempts: dict[str, float] = {}
        self._last_jobs: dict[str, float] = {}
        self._last_active_jobs: dict[str, float] = {}
        self._schema_position: int = 0
        self._last_queues: float | None = None
        self._last_aws: float | None = None
        self._metadata: OrderedDict[tuple[str, str, str], tuple[str, float, int]] = (
            OrderedDict()
        )
        self._last_issue_level: int = 0
        self._scanned_at: dict[tuple[str, str], datetime] = {}
        self._sweeps: dict[tuple[str, str], tuple[float, int]] = {}
        self._source_success: dict[str, float] = {}
        self.source_errors: int = 0
        self._discovery_failures: int = 0
        self.queue_errors: int = 0
        self.aws_errors: int = 0
        self.aws_consecutive_errors: int = 0
        self.last_aws_success_at: str | None = None

    def _partition(self, schemas: list[str]) -> list[str]:
        return [
            schema
            for schema in schemas[:10000]
            if int.from_bytes(hashlib.sha256(schema.encode()).digest()[:8])
            % self.shard_count
            == self.shard_index
        ]

    def _event(
        self,
        event_type: str,
        data: dict[str, Any],
        schema: str,
        revision: datetime,
        entity: str,
        *,
        durable_id: bool,
        observed_at: datetime | None = None,
    ) -> bool:
        identity: str = f"{self.client.config.deployment_id}:{schema}:{event_type}:{entity}:{revision.isoformat()}:{SOURCE_EVENT_REVISION}"
        if durable_id and observed_at is not None:
            # Active source rows may update counters without a revision timestamp.
            # Only already-sanitized structural state participates in identity.
            identity += ":" + self.client.fingerprint(
                json.dumps(data, sort_keys=True, separators=(",", ":"))
            )
        event_id: str | None = (
            str(
                uuid.uuid5(
                    uuid.UUID(self.client.config.customer_uuid),
                    identity,
                )
            )
            if durable_id
            else None
        )
        metadata_key: tuple[str, str, str] = (event_type, schema, entity)
        signature: str = ""
        observed: float = time.monotonic()
        loss: int = self.client.dropped + self.client.rejected
        if event_type == "tenant_domain" or (
            event_type == "license" and data.get("action") == "snapshot"
        ):
            signature = json.dumps(data, sort_keys=True, separators=(",", ":"))
            previous: tuple[str, float, int] | None = self._metadata.get(metadata_key)
            if (
                previous
                and previous[0] == signature
                and observed - previous[1] < 21600
                and previous[2] == loss
                and not self.client.failures
            ):
                return True
        emitted: bool = self.client.emit(
            event_type,
            data,
            tenant_id=schema if MULTI_TENANT else None,
            event_id=event_id,
            occurred_at=(observed_at or revision).timestamp(),
            revision=SOURCE_EVENT_REVISION,
        )
        if emitted and signature:
            self._metadata[metadata_key] = (signature, observed, loss)
            self._metadata.move_to_end(metadata_key)
            while len(self._metadata) > 20000:
                self._metadata.popitem(last=False)
        return emitted

    def _note_scan(self, schema: str, kind: str, rows: list[dict[str, Any]]) -> None:
        # Source transaction time of this read; all rows of one read share it.
        scanned: object = rows[-1].get("source_time") if rows else None
        if isinstance(scanned, datetime):
            self._scanned_at[(schema, kind)] = scanned

    def _edge_start(
        self, schema: str, kind: str, current: datetime, now: float
    ) -> datetime:
        """Where the next read starts after a cursor reaches the live edge.

        Normally a short overlap before the last read, on the source clock, so rows
        that commit late are read again. Every six hours, and after the service
        deferred events until they expired, a 24-hour sweep resends recent rows;
        durable event IDs let the service deduplicate them.
        """
        expired: int = self.client.expired
        swept_at, swept_expired = self._sweeps.setdefault(
            (schema, kind), (now, expired)
        )
        if now - swept_at >= _REPAIR_INTERVAL_SECONDS or expired != swept_expired:
            self._sweeps[(schema, kind)] = (now, expired)
            return datetime.now(timezone.utc) - _REPAIR_WINDOW
        scanned: datetime | None = self._scanned_at.get((schema, kind))
        return scanned - _REPAIR_OVERLAP if scanned is not None else current

    def collect_email_domains(self, schema: str, now: float) -> bool:
        if not poll_due(
            self._last_domains.get(schema),
            now,
            CONNECTOR_INTERVAL_SECONDS,
        ):
            return False
        try:
            rows: list[dict[str, Any]] = email_domain_page(
                self.engine, schema, self._domain_cursor.get(schema, "")
            )
        except SQLAlchemyError:
            self.email_domain_errors += 1
            self._last_domains[schema] = now
            return False
        for row in rows:
            if not self._event(
                "tenant_domain",
                {
                    "domain": row["domain"],
                    "first_signup_at": _iso(row["first_signup_at"]),
                },
                schema,
                datetime.now(timezone.utc),
                row["domain"],
                durable_id=False,
            ):
                # An invalid domain must not stop later inventory pages.
                if normalize_email_domain(row["domain"]):
                    break
            self._domain_cursor[schema] = row["domain"]
        else:
            if len(rows) < 200:
                self._domain_cursor[schema] = ""
                self._last_domains[schema] = now
        return True

    def collect_license(self, schema: str, now: float) -> bool:
        if not poll_due(
            self._last_license.get(schema),
            now,
            CONNECTOR_INTERVAL_SECONDS,
        ):
            return False
        try:
            row: dict[str, Any] = license_snapshot(self.engine, schema)
        except SQLAlchemyError:
            self.license_errors += 1
            self._last_license[schema] = now
            return False
        sent: bool = self._event(
            "license",
            {
                "license_present": row["license_present"],
                "action": "snapshot",
                "first_set_at": _iso(row["first_set_at"]),
            },
            schema,
            datetime.now(timezone.utc),
            "license",
            durable_id=False,
        )
        if sent:
            self._last_license[schema] = now
        return sent

    def collect_stages(self, schema: str, now: float) -> None:
        if not poll_due(
            self._last_stages.get(schema),
            now,
            CONNECTOR_INTERVAL_SECONDS,
        ):
            return
        scan_started: datetime = datetime.now(timezone.utc)
        oldest: datetime = scan_started - _STAGE_HORIZON
        since, after_id = self._stage_cursor.get(schema, (oldest, 0))
        try:
            rows: list[dict[str, Any]] = stage_metric_page(
                self.engine, schema, max(since, oldest), after_id
            )
            for row in rows:
                data: dict[str, Any] = {
                    key: row[key]
                    for key in (
                        "attempt_id",
                        "connector_id",
                        "cc_pair_id",
                        "event_count",
                        "total_duration_ms",
                        "min_duration_ms",
                        "max_duration_ms",
                        "m2_duration_ms",
                    )
                }
                data.update(
                    stage_name=row["stage"],
                    connector_type=row["connector_type"].lower(),
                    first_event_at=_iso(row["first_event_at"]),
                    last_event_at=_iso(row["last_event_at"]),
                )
                updated: datetime = row["last_event_at"]
                if not self._event(
                    "stage",
                    data,
                    schema,
                    updated,
                    str(row["id"]),
                    durable_id=True,
                    observed_at=updated,
                ):
                    return
                self._stage_cursor[schema] = (updated, row["id"])
            if len(rows) < 200:
                # Reconcile small timestamp overlaps, including a source commit arriving late.
                self._stage_cursor[schema] = (scan_started - timedelta(minutes=5), 0)
                self._last_stages[schema] = now
        except Exception:
            self.stage_errors += 1
            self._last_stages[schema] = now

    def collect_one_schema(self) -> bool:
        if not self.schemas:
            return False
        schema: str = self.schemas[self._schema_position % len(self.schemas)]
        self._schema_position += 1
        now: float = time.monotonic()
        if self._failed_schema.get(schema, (0, 0))[0] > now:
            return False
        self.collect_stages(schema, now)
        collected: bool = self.collect_email_domains(schema, now)
        collected = self.collect_license(schema, now) or collected
        if poll_due(
            self._last_connectors.get(schema),
            now,
            CONNECTOR_INTERVAL_SECONDS,
        ):
            rows: list[dict[str, Any]] | None = connector_page(
                self.engine, schema, self._connector_cursor.get(schema, 0)
            )
            collected = True
            for row in rows:
                if not self._event(
                    "connector",
                    safe_connector_data(row, self.client),
                    schema,
                    datetime.now(timezone.utc),
                    str(row["cc_pair_id"]),
                    durable_id=False,
                ):
                    break
                self._connector_cursor[schema] = row["cc_pair_id"]
            else:
                if len(rows) < 200:
                    self._connector_cursor[schema] = 0
                    self._last_connectors[schema] = now
        oldest: datetime = datetime.now(timezone.utc) - _HISTORY_HORIZON
        since, after_id = self._attempt_cursor.get(schema, (oldest, 0))
        interval: int = CONNECTOR_INTERVAL_SECONDS
        rows = (
            attempt_page(self.engine, schema, since, after_id)
            if poll_due(self._last_attempts.get(schema), now, interval)
            else None
        )
        self._note_scan(schema, "attempt", rows or [])
        collected = collected or rows is not None
        for row in rows or []:
            state: str = row["state"]
            updated: datetime = row["time_updated"]
            data: dict[str, Any] = {
                key: row[key]
                for key in {
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
                }
            }
            data["counter_mode"] = "snapshot"
            data["connector_type"] = row["connector_type"].lower()
            for key in {"started_at", "last_progress_at", "last_heartbeat_at"}:
                data[key] = _iso(row.get(key))
            if state in {
                "success",
                "failed",
                "completed_with_errors",
                "canceled",
                "interrupted",
            }:
                data["ended_at"] = _iso(updated)
            if row["has_error"] or row["error_count"]:
                data.update(safe_attempt_error_data(row, self.client))
            if not self._event(
                "attempt",
                data,
                schema,
                updated,
                str(row["attempt_id"]),
                durable_id=True,
            ):
                break
            self._attempt_cursor[schema] = (updated, row["attempt_id"])
        else:
            if rows is not None and len(rows) < 200:
                self._attempt_cursor[schema] = (
                    self._edge_start(schema, "attempt", since, now),
                    0,
                )
                self._last_attempts[schema] = now
        job_since, job_after_id = self._job_cursor.get(schema, (oldest, ""))
        observed_at: datetime = datetime.now(timezone.utc)
        historical: list[dict[str, Any]] | None = (
            job_page(self.engine, schema, job_since, job_after_id)
            if poll_due(self._last_jobs.get(schema), now, interval)
            else None
        )
        self._note_scan(schema, "job", historical or [])
        active: list[dict[str, Any]] | None = (
            job_page(
                self.engine,
                schema,
                oldest,
                self._active_job_cursor.get(schema, ""),
                active_only=True,
            )
            if poll_due(self._last_active_jobs.get(schema), now, interval)
            else None
        )
        collected = collected or historical is not None or active is not None
        job_rows: list[tuple[dict[str, Any], bool]] = [
            (row, False) for row in historical or []
        ] + [(row, True) for row in active or []]
        for row, active_only in job_rows:
            data = {
                "job_id": row["id"],
                "entity_id": row["entity_id"],
                "job_type": row["job_type"],
                "state": row["state"],
                "docs_processed": row["docs_processed"] or 0,
                "users_processed": row["users_processed"] or 0,
                "groups_processed": row["groups_processed"] or 0,
                "memberships_synced": row["memberships_synced"] or 0,
                "started_at": _iso(row["started_at"]),
                "ended_at": _iso(row["ended_at"]),
                "error_count": max(
                    row["error_count"] or 0, int(row["state"] == "failed")
                ),
            }
            if row["ended_at"] and row["started_at"]:
                data["duration_ms"] = max(
                    0, (row["ended_at"] - row["started_at"]).total_seconds() * 1000
                )
            if row["id"].split(":", 1)[0] in {
                "permission",
                "group",
                "hierarchy",
                "port",
            }:
                data["cc_pair_id"] = row["entity_id"]
            if not self._event(
                "job",
                data,
                schema,
                row["revision_at"],
                str(row["id"]),
                durable_id=True,
                observed_at=observed_at
                if row["state"] in {"not_started", "in_progress", "scheduled"}
                else None,
            ):
                break
            if active_only:
                self._active_job_cursor[schema] = row["id"]
            else:
                self._job_cursor[schema] = (row["revision_at"], row["id"])
        else:
            if historical is not None and len(historical) < 200:
                self._job_cursor[schema] = (
                    self._edge_start(schema, "job", job_since, now),
                    "",
                )
                self._last_jobs[schema] = now
            if active is not None and len(active) < 200:
                self._active_job_cursor[schema] = ""
                self._last_active_jobs[schema] = now
        return collected

    def collect_queues(self) -> None:
        if not poll_due(
            self._last_queues,
            time.monotonic(),
            QUEUE_INTERVAL_SECONDS,
        ):
            return
        from redis import Redis

        from onyx.configs.constants import (
            CELERY_SEPARATOR,
            OnyxCeleryPriority,
            OnyxCeleryQueues,
        )

        url: str | None = os.environ.get("ONYX_TELEMETRY_REDIS_URL")
        tls_options: dict[str, Any] = {}
        if not url and (not self.client.config.auto_enroll or self.shard_index != 0):
            return
        if not url:
            from urllib.parse import quote

            from onyx.configs.app_configs import (
                REDIS_DB_NUMBER_CELERY,
                REDIS_HOST,
                REDIS_PASSWORD,
                REDIS_PORT,
                REDIS_SSL,
                REDIS_SSL_CA_CERTS,
                REDIS_SSL_CERT_REQS,
                REDIS_SSL_CERTFILE,
                REDIS_SSL_CHECK_HOSTNAME,
                REDIS_SSL_KEYFILE,
                USE_REDIS_IAM_AUTH,
            )

            if USE_REDIS_IAM_AUTH:
                return
            scheme: str = "rediss" if REDIS_SSL else "redis"
            password: str = (
                ":" + quote(REDIS_PASSWORD, safe="") + "@" if REDIS_PASSWORD else ""
            )
            url = f"{scheme}://{password}{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB_NUMBER_CELERY}"
            if REDIS_SSL:
                tls_options = {
                    "ssl_cert_reqs": REDIS_SSL_CERT_REQS,
                    "ssl_check_hostname": REDIS_SSL_CHECK_HOSTNAME,
                    "ssl_ca_certs": REDIS_SSL_CA_CERTS,
                    "ssl_certfile": REDIS_SSL_CERTFILE,
                    "ssl_keyfile": REDIS_SSL_KEYFILE,
                }
        # Connection failures follow the same bounded poll cadence as success.
        self._last_queues = time.monotonic()
        redis: Redis = Redis.from_url(
            url,
            socket_connect_timeout=0.2,
            socket_timeout=0.2,
            max_connections=1,
            **tls_options,
        )
        try:
            queues: list[str] = [
                queue
                for key, queue in vars(OnyxCeleryQueues).items()
                if not key.startswith("_") and isinstance(queue, str)
            ]
            priorities: int = len(OnyxCeleryPriority)
            with redis.pipeline(transaction=False) as pipeline:
                for queue in queues:
                    for priority in range(priorities):
                        pipeline.llen(
                            queue
                            if priority == 0
                            else queue + CELERY_SEPARATOR + str(priority)
                        )
                lengths: list[int] = pipeline.execute()
            for position, queue in enumerate(queues):
                self.client.emit(
                    "queue",
                    {
                        "queue": queue,
                        "depth": sum(
                            lengths[position * priorities : (position + 1) * priorities]
                        ),
                        "shared": True,
                    },
                )
        finally:
            redis.close()

    def tick(self) -> None:
        now: float = time.monotonic()
        if self._discover and poll_due(self._last_discovery, now, 60):
            try:
                self.schemas = self._partition(tenant_schemas(self.engine))
                self._discovery_failures = 0
            except Exception:
                self.source_errors += 1
                self._discovery_failures = min(8, self._discovery_failures + 1)
            self._last_discovery = now
        started: float = time.monotonic()
        for _ in range(min(10, len(self.schemas))):
            schema: str = self.schemas[self._schema_position % len(self.schemas)]
            if self._failed_schema.get(schema, (0, 0))[0] > time.monotonic():
                self._schema_position += 1
                continue
            try:
                if self.collect_one_schema():
                    self._failed_schema.pop(schema, None)
                    self._source_success[schema] = time.time()
            except Exception:
                # No SQL, endpoint, identifiers, or exception strings are logged.
                failures: int = min(self._failed_schema.get(schema, (0, 0))[1] + 1, 8)
                self._failed_schema[schema] = (
                    time.monotonic() + min(300, 2**failures),
                    failures,
                )
                self.source_errors += 1
            if time.monotonic() - started >= 1:
                break
        try:
            self.collect_queues()
        except Exception:
            self.queue_errors += 1
        if poll_due(
            self._last_aws,
            time.monotonic(),
            RESOURCE_INTERVAL_SECONDS,
        ):
            try:
                from onyx.utils.fleet_telemetry_aws import collect_aws_resources

                result: bool | None = collect_aws_resources(self.client)
                if result is True:
                    self.aws_consecutive_errors = 0
                    self.last_aws_success_at = datetime.now(timezone.utc).isoformat()
                elif result is False:
                    self.aws_errors += 1
                    self.aws_consecutive_errors += 1
            except Exception:
                self.aws_errors += 1
                self.aws_consecutive_errors += 1
            self._last_aws = time.monotonic()
        if self.shard_index == 0 and poll_due(
            self._last_opensearch,
            time.monotonic(),
            RESOURCE_INTERVAL_SECONDS,
        ):
            self._last_opensearch = time.monotonic()
            try:
                from onyx.utils.fleet_telemetry_opensearch import (
                    collect_opensearch_health,
                )

                collect_opensearch_health(self.client)
            except Exception:
                self.source_errors += 1
        self.client.health = {
            "stage_errors": self.stage_errors,
            "email_domain_errors": self.email_domain_errors,
            "license_errors": self.license_errors,
            "source_errors": self.source_errors,
            "source_consecutive_errors": max(
                self._discovery_failures,
                max(
                    (failures for _, failures in self._failed_schema.values()),
                    default=0,
                ),
            ),
            "last_source_success_at": datetime.fromtimestamp(
                max(self._source_success.values()), timezone.utc
            ).isoformat()
            if self._source_success
            else None,
            "queue_errors": self.queue_errors,
            "kubernetes_errors": self.client.health.get("kubernetes_errors", 0),
            "schema_count": len(self.schemas),
            "aws_errors": self.aws_errors,
            "aws_consecutive_errors": self.aws_consecutive_errors,
            "last_aws_success_at": self.last_aws_success_at,
        }
        level: int = self.client.health["source_consecutive_errors"]
        if level >= 3 and self._last_issue_level < 3:
            # The sender reports health on its own cadence; failures report at once.
            self.client.emit(
                "heartbeat",
                {**self.client.delivery_health(), **self.client.health},
            )
        self._last_issue_level = level


def main() -> None:
    parser: argparse.ArgumentParser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args: argparse.Namespace = parser.parse_args()
    stopped: threading.Event = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stopped.set())
    signal.signal(signal.SIGINT, lambda *_: stopped.set())
    if telemetry_disabled():
        # Keep long-running containers idle instead of entering a restart loop.
        if not args.once:
            stopped.wait()
        return
    # Select the edition before identity storage resolves the secret codec, like
    # every other Onyx process does at startup.
    set_is_ee_if_available()
    client: BoundedTelemetry | None = start_telemetry("collector")
    while client is None and not stopped.wait(2):
        client = start_telemetry("collector")
    if client is None:
        stop_telemetry()
        return
    database_url: str = source_database_url()
    schemas: list[str] = [
        value
        for value in os.environ.get(
            "ONYX_TELEMETRY_SCHEMAS", "" if MULTI_TENANT else "public"
        ).split(",")
        if value
    ]
    collector: FleetCollector = FleetCollector(client, database_url, schemas)
    from onyx.utils.fleet_telemetry_kubernetes import KubernetesCollector

    kubernetes: KubernetesCollector | None = (
        KubernetesCollector(client)
        if os.environ.get("ONYX_TELEMETRY_KUBERNETES", "").lower() == "true"
        else None
    )
    try:
        while not stopped.is_set():
            collector.tick()
            if kubernetes is not None:
                kubernetes.tick()
            if args.once:
                # One-shot runs report collector health and wait briefly for delivery.
                client.emit("heartbeat", {**client.delivery_health(), **client.health})
                break
            stopped.wait(2)
    finally:
        collector.engine.dispose()
        stop_telemetry(flush_timeout=EXIT_FLUSH_SECONDS if args.once else 0.0)


if __name__ == "__main__":
    main()
