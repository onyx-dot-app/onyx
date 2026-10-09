"""Collector reads and one collection pass against a migrated local PostgreSQL.

Each test copies the source tables into a new schema and reads it as a tenant.
"""

import json
import uuid
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import Mock

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.enums import SyncType
from onyx.db.fleet_telemetry import (
    attempt_rows,
    email_domain_rows,
    job_rows,
    license_row,
    limit_statement_time,
    stage_rows,
)
from onyx.db.sync_record import insert_sync_record
from onyx.utils import fleet_telemetry_collector as collector
from tests.unit.fakes import FakeCache
from tests.utils.fleet_telemetry import make_sender

_TABLES: tuple[str, ...] = (
    "license",
    "connector",
    "connector_credential_pair",
    "index_attempt",
    "index_attempt_errors",
    "index_attempt_stage_metric",
    "sync_record",
    "doc_permission_sync_attempt",
    "external_group_permission_sync_attempt",
    "hierarchy_fetch_attempt",
    "port_attempt",
    "key_value_store",
)

_ROWS: str = """
INSERT INTO connector (id, name, source, connector_specific_config, refresh_freq)
VALUES
  (1, 'PRIVATE drive', 'GOOGLE_DRIVE',
   '{"folder_paths": ["PRIVATE FOLDER"], "batch_size": 16}', 600),
  (2, 'PRIVATE wiki', 'CONFLUENCE', '{"space": "PRIVATE"}', NULL);
INSERT INTO connector_credential_pair
  (id, name, status, connector_id, credential_id, access_type, total_docs_indexed)
VALUES
  (1, 'PRIVATE drive', 'ACTIVE', 1, 1, 'SYNC', 100),
  (2, 'PRIVATE wiki', 'PAUSED', 2, 1, 'PUBLIC', 0);
INSERT INTO index_attempt
  (id, connector_credential_pair_id, from_beginning, status, error_msg,
   total_docs_indexed, total_chunks, total_batches, completed_batches,
   time_updated, is_synthetic_seed)
VALUES
  (1, 1, true, 'FAILED', 'PRIVATE: 401 unauthorized', 20, 30, 4, 2, now(), false),
  (2, 1, false, 'IN_PROGRESS', NULL, 5, 9, 4, 1, now() - interval '3 days', false),
  (3, 2, false, 'SUCCESS', NULL, 1, 1, 1, 1, now() - interval '3 days', false),
  (4, 1, false, 'IN_PROGRESS', NULL, 0, 0, 0, 0, now(), true);
INSERT INTO index_attempt_errors
  (index_attempt_id, connector_credential_pair_id, failure_message, error_type,
   is_resolved)
VALUES
  (1, 1, 'PRIVATE document failed', 'ReadTimeout', false),
  (1, 1, 'PRIVATE resolved failure', 'ValueError', true);
INSERT INTO index_attempt_stage_metric
  (index_attempt_id, stage, event_count, total_duration_ms, m2_duration_ms,
   min_duration_ms, max_duration_ms, time_first_event, time_last_event)
VALUES
  (2, 'EMBEDDING', 2, 300, 5000, 100, 200, now() - interval '2 minutes', now()),
  (2, 'CHUNKING', 1, 10, 0, 10, 10, now() - interval '3 days',
   now() - interval '3 days');
INSERT INTO doc_permission_sync_attempt
  (id, connector_credential_pair_id, status, total_docs_synced,
   docs_with_permission_errors, time_started, time_finished)
VALUES
  (1, 1, 'SUCCESS', 99, 0, now() - interval '5 minutes', now()),
  (2, 1, 'IN_PROGRESS', 3, 0, now() - interval '90 days', NULL);
INSERT INTO external_group_permission_sync_attempt
  (id, connector_credential_pair_id, status, total_users_processed,
   total_groups_processed, total_group_memberships_synced, time_started,
   time_finished)
VALUES (1, 1, 'SUCCESS', 5, 2, 7, now() - interval '5 minutes', now());
INSERT INTO hierarchy_fetch_attempt (id, connector_credential_pair_id, status)
VALUES ('6f1c62c4-6e4b-4f35-9d4b-1d2f0c7b8a10', 1, 'IN_PROGRESS');
INSERT INTO port_attempt (id, cc_pair_id, search_settings_id, status, error_msg)
VALUES (1, 1, 1, 'FAILED', 'PRIVATE port failure');
INSERT INTO license (license_data) VALUES ('PRIVATE LICENSE');
INSERT INTO "user" (email, created_at, account_type)
VALUES
  ('PRIVATE.FIRST@Poc.Example.COM', '2020-01-01', 'STANDARD'),
  ('PRIVATE.SECOND@onyx.app', '2021-01-01', 'STANDARD'),
  ('PRIVATE.THIRD@poc.example.com', '2022-01-01', 'STANDARD'),
  ('PRIVATE.BOT@excluded.example.com', '2019-01-01', 'BOT');
"""


@pytest.fixture
def schema(db_session: Session) -> Generator[str, None, None]:
    name: str = "telemetry_test_" + uuid.uuid4().hex[:12]
    db_session.execute(text(f'CREATE SCHEMA "{name}"'))
    for table in _TABLES:
        db_session.execute(
            text(f'CREATE TABLE "{name}".{table} (LIKE public.{table} INCLUDING ALL)')
        )
    # The collector reads three columns of the user table.
    db_session.execute(
        text(
            f'CREATE TABLE "{name}"."user" '
            "(email text, created_at timestamptz, account_type text)"
        )
    )
    db_session.execute(text(f'SET LOCAL search_path TO "{name}"'))
    db_session.execute(text(_ROWS))
    db_session.commit()
    try:
        yield name
    finally:
        db_session.execute(text(f'DROP SCHEMA "{name}" CASCADE'))
        db_session.commit()


def test_reads_return_changed_and_running_work_only(schema: str) -> None:
    since: datetime = datetime.now(timezone.utc) - timedelta(hours=1)
    with get_session_with_tenant(tenant_id=schema) as db_session:
        limit_statement_time(db_session)
        attempts: dict[int, dict[str, Any]] = {
            row["attempt_id"]: row for row in attempt_rows(db_session, since)
        }
        stages: list[dict[str, Any]] = stage_rows(db_session, list(attempts), since)
        jobs: dict[str, dict[str, Any]] = {
            row["job_id"]: row for row in job_rows(db_session, since)
        }
        domains: list[dict[str, Any]] = email_domain_rows(db_session)
        license: dict[str, Any] = license_row(db_session)
    # Finished work outside the window and synthetic seeds are not read. Changed
    # rows come first, oldest first, then running rows from before the window.
    assert list(attempts) == [1, 2]
    assert attempts[1]["error_count"] == 1
    assert attempts[1]["item_error_type"] == "ReadTimeout"
    assert [(row["attempt_id"], row["stage"].value) for row in stages] == [
        (2, "EMBEDDING")
    ]
    assert set(jobs) == {
        "permission:1",
        "permission:2",
        "group:1",
        "hierarchy:6f1c62c4-6e4b-4f35-9d4b-1d2f0c7b8a10",
        "port:1",
    }
    assert jobs["permission:2"]["state"] == "in_progress"
    assert [job for job in jobs if job.startswith("permission:")] == [
        "permission:1",
        "permission:2",
    ]
    assert jobs["group:1"]["memberships_synced"] == 7
    assert jobs["port:1"]["error_count"] == 1
    assert [(row["domain"], row["first_signup_at"].year) for row in domains] == [
        ("onyx.app", 2021),
        ("poc.example.com", 2020),
    ]
    assert license["license_present"] is True


def test_sync_canceled_by_a_new_run_is_read_as_canceled(schema: str) -> None:
    with get_session_with_tenant(tenant_id=schema) as db_session:
        # Text SQL is not schema-translated, so it names the schema.
        stale_id: int = db_session.execute(
            text(
                f'INSERT INTO "{schema}".sync_record '
                "(entity_id, sync_type, sync_status, num_docs_synced, sync_start_time) "
                "VALUES (7, 'DOCUMENT_SET', 'IN_PROGRESS', 0, now() - interval '3 days') "
                "RETURNING id"
            )
        ).scalar_one()
        db_session.commit()
        insert_sync_record(db_session, 7, SyncType.DOCUMENT_SET)
        jobs: list[dict[str, Any]] = job_rows(
            db_session, datetime.now(timezone.utc) - timedelta(minutes=10)
        )
    syncs: dict[str, str] = {
        row["job_id"]: row["state"] for row in jobs if row["job_id"].startswith("sync:")
    }
    assert syncs.pop(f"sync:{stale_id}") == "canceled"
    assert list(syncs.values()) == ["in_progress"]


def test_a_slow_read_is_stopped(schema: str) -> None:
    with get_session_with_tenant(tenant_id=schema) as db_session:
        limit_statement_time(db_session)
        with pytest.raises(OperationalError):
            db_session.execute(text("SELECT pg_sleep(3)"))


def test_one_pass_sends_only_safe_events(
    schema: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    sender = make_sender(capacity=256)
    monkeypatch.setattr(collector, "get_sender", lambda: sender)
    monkeypatch.setattr(collector, "get_cache_backend", Mock(return_value=FakeCache()))
    collector.collect_snapshots(schema)
    events: list[dict[str, Any]] = sender._take_batch()
    assert sender.health["source_consecutive_errors"] == 0
    assert sender.invalid == 0
    by_type: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        by_type.setdefault(event["event_type"], []).append(event["data"])
    assert {key: len(value) for key, value in by_type.items()} == {
        "connector": 2,
        "tenant_domain": 2,
        "license": 1,
        "attempt": 2,
        "stage": 1,
        "job": 5,
    }
    failed: dict[str, Any] = next(
        data for data in by_type["attempt"] if data["state"] == "failed"
    )
    assert failed["error_code"] == "auth"
    assert by_type["connector"][0]["metadata"]["permission_sync_enabled"] is True
    assert "PRIVATE" not in json.dumps(events)


@pytest.mark.usefixtures("db_session")
def test_deployment_key_is_persistent_and_race_safe(
    schema: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from onyx.db import fleet_enrollment

    monkeypatch.setattr(fleet_enrollment, "POSTGRES_DEFAULT_SCHEMA", schema)
    # Processes that start together must all report as one deployment.
    with ThreadPoolExecutor(max_workers=4) as workers:
        keys: list[str] = list(
            workers.map(
                lambda _: fleet_enrollment.get_or_create_deployment_key(), range(4)
            )
        )
    assert len(set(keys)) == 1 and len(keys[0]) == 64
    assert fleet_enrollment.get_or_create_deployment_key() == keys[0]
