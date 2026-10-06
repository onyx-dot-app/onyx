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
from datetime import datetime, timedelta, timezone
from typing import Any

from onyx.db.fleet_telemetry import (
    SAFE_BOOLEAN_SETTINGS,
    SAFE_NUMBER_SETTINGS,
    attempt_page,
    collector_engine,
    connector_page,
    job_page,
    tenant_schemas,
)
from onyx.utils.fleet_telemetry import (
    BoundedTelemetry,
    poll_due,
    start_telemetry,
    stop_telemetry,
)
from shared_configs.configs import MULTI_TENANT

SOURCE_EVENT_REVISION = 1


def _iso(value: Any) -> str | None:
    if isinstance(value, datetime):
        return (
            value.replace(tzinfo=timezone.utc).isoformat()
            if value.tzinfo is None
            else value.isoformat()
        )
    return None


_ERROR_PATTERNS = (
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
    candidate = " ".join(
        sample[:2048] for sample in samples if isinstance(sample, str)
    )[:6144]
    for category, pattern in _ERROR_PATTERNS:
        if re.search(pattern, candidate, re.IGNORECASE):
            return category
    return "internal"


def safe_attempt_error_data(
    row: dict[str, Any], client: BoundedTelemetry
) -> dict[str, Any]:
    category = classify_local_error(
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
    stage = {"embedding": "embed", "index_write": "write", "parse": "prepare"}.get(
        category
    )
    if stage is not None:
        data["stage"] = stage
    return data


def safe_connector_data(
    row: dict[str, Any], client: BoundedTelemetry
) -> dict[str, Any]:
    raw = row.get("metadata", {})
    allowed = set(SAFE_BOOLEAN_SETTINGS + SAFE_NUMBER_SETTINGS) | {
        "selection_count",
        "include_rule_count",
        "exclude_rule_count",
        "include_pattern_count",
        "exclude_pattern_count",
        "file_type_count",
        "has_time_filter",
    }
    metadata = (
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
        value = row.get(key)
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
        self.client = client
        self.engine = collector_engine(database_url)
        self.schemas = schemas
        self.shard_count = max(
            1, min(1000, int(os.environ.get("ONYX_TELEMETRY_SCHEMA_SHARD_COUNT", "1")))
        )
        self.shard_index = int(os.environ.get("ONYX_TELEMETRY_SCHEMA_SHARD_INDEX", "0"))
        if not 0 <= self.shard_index < self.shard_count:
            raise ValueError("Invalid collector shard")
        self.schemas = self._partition(schemas)
        self._last_discovery: float | None = None
        self._discover = MULTI_TENANT and "ONYX_TELEMETRY_SCHEMAS" not in os.environ
        self._failed_schema: dict[str, tuple[float, int]] = {}
        self._connector_cursor: dict[str, int] = {}
        self._last_connectors: dict[str, float] = {}
        self._attempt_cursor: dict[str, tuple[datetime, int]] = {}
        self._job_cursor: dict[str, tuple[datetime, str]] = {}
        self._active_job_cursor: dict[str, str] = {}
        self._last_attempts: dict[str, float] = {}
        self._last_jobs: dict[str, float] = {}
        self._last_active_jobs: dict[str, float] = {}
        self._schema_position = 0
        self._last_queues: float | None = None
        self._last_aws: float | None = None
        self._last_health: float | None = None
        self._last_issue_level = 0
        self._source_success: dict[str, float] = {}
        self.source_errors = 0
        self._discovery_failures = 0
        self.queue_errors = 0
        self.aws_errors = 0
        self.aws_consecutive_errors = 0
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
        identity = f"{self.client.config.deployment_id}:{schema}:{event_type}:{entity}:{revision.isoformat()}:{SOURCE_EVENT_REVISION}"
        if durable_id and observed_at is not None:
            # Active source rows may update counters without a revision timestamp.
            # Only already-sanitized structural state participates in identity.
            identity += ":" + self.client.fingerprint(
                json.dumps(data, sort_keys=True, separators=(",", ":"))
            )
        event_id = (
            str(
                uuid.uuid5(
                    uuid.UUID(self.client.config.customer_uuid),
                    identity,
                )
            )
            if durable_id
            else None
        )
        return self.client.emit(
            event_type,
            data,
            tenant_id=schema if MULTI_TENANT else None,
            event_id=event_id,
            occurred_at=(observed_at or revision).timestamp(),
            revision=SOURCE_EVENT_REVISION,
        )

    def collect_one_schema(self) -> bool:
        if not self.schemas:
            return False
        schema = self.schemas[self._schema_position % len(self.schemas)]
        self._schema_position += 1
        now = time.monotonic()
        if self._failed_schema.get(schema, (0, 0))[0] > now:
            return False
        collected = False
        if poll_due(
            self._last_connectors.get(schema),
            now,
            self.client.settings["connector_interval_seconds"],
        ):
            rows = connector_page(
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
        oldest = datetime.now(timezone.utc) - timedelta(days=184)
        since, after_id = self._attempt_cursor.get(schema, (oldest, 0))
        interval = self.client.settings["connector_interval_seconds"]
        rows = (
            attempt_page(self.engine, schema, since, after_id)
            if poll_due(self._last_attempts.get(schema), now, interval)
            else None
        )
        collected = collected or rows is not None
        for row in rows or []:
            state = row["state"]
            updated = row["time_updated"]
            data = {
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
                # Re-read a bounded repair window after reaching the live edge.
                self._attempt_cursor[schema] = (
                    datetime.now(timezone.utc) - timedelta(hours=24),
                    0,
                )
                self._last_attempts[schema] = now
        job_since, job_after_id = self._job_cursor.get(schema, (oldest, ""))
        observed_at = datetime.now(timezone.utc)
        historical = (
            job_page(self.engine, schema, job_since, job_after_id)
            if poll_due(self._last_jobs.get(schema), now, interval)
            else None
        )
        active = (
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
        job_rows = [(row, False) for row in historical or []] + [
            (row, True) for row in active or []
        ]
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
                    datetime.now(timezone.utc) - timedelta(hours=24),
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
            self.client.settings["queue_interval_seconds"],
        ):
            return
        from redis import Redis

        from onyx.configs.constants import (
            CELERY_SEPARATOR,
            OnyxCeleryPriority,
            OnyxCeleryQueues,
        )

        url = os.environ.get("ONYX_TELEMETRY_REDIS_URL")
        if not url:
            return
        # Connection failures follow the same bounded poll cadence as success.
        self._last_queues = time.monotonic()
        redis = Redis.from_url(
            url, socket_connect_timeout=0.2, socket_timeout=0.2, max_connections=1
        )
        try:
            queues = [
                queue
                for key, queue in vars(OnyxCeleryQueues).items()
                if not key.startswith("_") and isinstance(queue, str)
            ]
            priorities = len(OnyxCeleryPriority)
            with redis.pipeline(transaction=False) as pipeline:
                for queue in queues:
                    for priority in range(priorities):
                        pipeline.llen(
                            queue
                            if priority == 0
                            else queue + CELERY_SEPARATOR + str(priority)
                        )
                lengths = pipeline.execute()
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
        if not self.client.settings["enabled"]:
            return
        now = time.monotonic()
        if self._discover and poll_due(self._last_discovery, now, 60):
            try:
                self.schemas = self._partition(tenant_schemas(self.engine))
                self._discovery_failures = 0
            except Exception:
                self.source_errors += 1
                self._discovery_failures = min(8, self._discovery_failures + 1)
            self._last_discovery = now
        started = time.monotonic()
        for _ in range(min(10, len(self.schemas))):
            schema = self.schemas[self._schema_position % len(self.schemas)]
            if self._failed_schema.get(schema, (0, 0))[0] > time.monotonic():
                self._schema_position += 1
                continue
            try:
                if self.collect_one_schema():
                    self._failed_schema.pop(schema, None)
                    self._source_success[schema] = time.time()
            except Exception:
                # No SQL, endpoint, identifiers, or exception strings are logged.
                failures = min(self._failed_schema.get(schema, (0, 0))[1] + 1, 8)
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
            self.client.settings["resource_interval_seconds"],
        ):
            try:
                from onyx.utils.fleet_telemetry_aws import collect_aws_resources

                result = collect_aws_resources(self.client)
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
        self.client.health = {
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
        level = self.client.health["source_consecutive_errors"]
        if poll_due(self._last_health, time.monotonic(), 60) or (
            level >= 3 and self._last_issue_level < 3
        ):
            self.client.emit(
                "heartbeat",
                {
                    "collector_enabled": True,
                    "config_revision": self.client.settings["config_revision"],
                    **self.client.delivery_health(),
                    **self.client.health,
                },
            )
            self._last_health = time.monotonic()
            self._last_issue_level = level


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    client = start_telemetry("collector")
    if client is None:
        raise SystemExit("Telemetry configuration is missing or invalid")
    database_url = os.environ.get("ONYX_TELEMETRY_DATABASE_URL")
    if not database_url:
        raise SystemExit("ONYX_TELEMETRY_DATABASE_URL is required")
    schemas = [
        value
        for value in os.environ.get("ONYX_TELEMETRY_SCHEMAS", "public").split(",")
        if value
    ]
    collector = FleetCollector(client, database_url, schemas)
    stopped = threading.Event()
    from onyx.utils.fleet_telemetry_kubernetes import KubernetesCollector

    kubernetes = (
        KubernetesCollector(client)
        if os.environ.get("ONYX_TELEMETRY_KUBERNETES", "").lower() == "true"
        else None
    )
    signal.signal(signal.SIGTERM, lambda *_: stopped.set())
    signal.signal(signal.SIGINT, lambda *_: stopped.set())
    try:
        while not stopped.is_set():
            collector.tick()
            if kubernetes is not None:
                kubernetes.tick()
            if args.once:
                client.flush_once()
                break
            stopped.wait(2)
    finally:
        collector.engine.dispose()
        stop_telemetry()


if __name__ == "__main__":
    main()
