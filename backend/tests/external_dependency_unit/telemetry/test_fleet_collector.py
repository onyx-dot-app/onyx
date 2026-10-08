"""Collector reads against a migrated local PostgreSQL.

Set ONYX_TELEMETRY_TEST_DB to read from another migrated source database.
"""

import json
import os
import time
import uuid
from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import InternalError
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import SYNC_DB_API, build_connection_string
from onyx.db.enums import SyncType
from onyx.db.fleet_telemetry import (
    active_job_page,
    collector_engine,
    connector_page,
    email_domain_page,
    job_page,
)
from onyx.db.sync_record import insert_sync_record
from onyx.utils.fleet_telemetry_collector import FleetCollector
from tests.utils.fleet_telemetry import make_sender


@pytest.fixture
def source_schema() -> Generator[tuple[str, str], None, None]:
    source_url = os.environ.get("ONYX_TELEMETRY_TEST_DB") or build_connection_string(
        db_api=SYNC_DB_API
    )
    schema = "telemetry_test_" + uuid.uuid4().hex[:12]
    engine = create_engine(source_url)
    tables = (
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
    )
    with engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        for table in tables:
            connection.execute(
                text(
                    f'CREATE TABLE "{schema}".{table} (LIKE public.{table} INCLUDING DEFAULTS)'
                )
            )
        connection.execute(
            text(f'''CREATE TABLE "{schema}"."user" (
            email text,created_at timestamptz,account_type text)''')
        )
        connection.execute(
            text(f'''INSERT INTO "{schema}"."user" VALUES
            ('PRIVATE FIRST@Poc.Example.COM','2020-01-01','STANDARD'),
            ('PRIVATE SECOND@onyx.app','2021-01-01','STANDARD'),
            ('PRIVATE THIRD@poc.example.com','2022-01-01','STANDARD'),
            ('PRIVATE BOT@excluded.example.com','2019-01-01','BOT')''')
        )
        connection.execute(
            text(f'''CREATE VIEW "{schema}".fleet_signup_email_domains WITH (security_barrier=true) AS
            SELECT lower(split_part(email,'@',2)) AS domain,min(created_at) AS first_signup_at
            FROM "{schema}"."user" WHERE account_type='STANDARD' AND email ~ '^[^@]+@[^@]+$'
            GROUP BY lower(split_part(email,'@',2))''')
        )
        connection.execute(
            text(f'INSERT INTO "{schema}".license (license_data) VALUES (:key)'),
            {"key": "PRIVATE LICENSE"},
        )
        connection.execute(
            text(f"""CREATE VIEW "{schema}".fleet_license_state WITH (security_barrier=true) AS
            SELECT coalesce(bool_or(length(license_data)>0),false) AS license_present,
            min(created_at) FILTER (WHERE length(license_data)>0) AS first_set_at
            FROM "{schema}".license""")
        )
        # Collection must not depend on obsolete connector columns.
        connection.execute(
            text(
                f'ALTER TABLE "{schema}".connector DROP COLUMN kg_processing_enabled, DROP COLUMN kg_coverage_days'
            )
        )
        for number in range(1, 251):
            connection.execute(
                text(f"""INSERT INTO "{schema}".connector
              (id,name,source,input_type,connector_specific_config,refresh_freq)
              VALUES (:id,'PRIVATE CONNECTOR','GOOGLE_DRIVE','LOAD_STATE',
              CAST(:config AS jsonb),600)"""),
                {
                    "id": number,
                    "config": json.dumps(
                        {
                            "folder_paths": ["PRIVATE FOLDER"],
                            "token": "PRIVATE TOKEN",
                            "batch_size": 16,
                            "include_shared_drives": True,
                        }
                    ),
                },
            )
            connection.execute(
                text(f"""INSERT INTO "{schema}".connector_credential_pair
              (id,name,status,connector_id,credential_id,access_type,total_docs_indexed)
              VALUES (:id,'PRIVATE CONNECTOR','ACTIVE',:id,123,'PUBLIC',100)"""),
                {"id": number},
            )
        connection.execute(
            text(f"""INSERT INTO "{schema}".index_attempt
          (id,connector_credential_pair_id,from_beginning,status,error_msg,new_docs_indexed,total_docs_indexed,total_chunks,total_batches,completed_batches)
          VALUES (1,1,true,'FAILED','401 unauthorized PRIVATE TOKEN PRIVATE FOLDER',10,20,30,4,2)""")
        )
        connection.execute(
            text(f"""INSERT INTO "{schema}".doc_permission_sync_attempt
          (id,connector_credential_pair_id,status,total_docs_synced,docs_with_permission_errors,time_started,time_finished)
          VALUES (1,1,'SUCCESS',99,0,now()-interval '5 minutes',now())""")
        )
        connection.execute(
            text(f"""INSERT INTO "{schema}".external_group_permission_sync_attempt
          (id,connector_credential_pair_id,status,total_users_processed,total_groups_processed,total_group_memberships_synced,time_started,time_finished)
          VALUES (1,1,'SUCCESS',5,2,7,now()-interval '5 minutes',now())""")
        )
        connection.execute(
            text(f"""INSERT INTO "{schema}".doc_permission_sync_attempt
          (id,connector_credential_pair_id,status,total_docs_synced,docs_with_permission_errors,time_started)
          VALUES (2,1,'IN_PROGRESS',3,0,now()-interval '90 days')""")
        )
    try:
        yield source_url, schema
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()


# The queue must hold every event of a full read: the schema has 250 connectors.
_CAPACITY: int = 1024


@pytest.mark.parametrize("uptime", [0.0, 120.0])
def test_bounded_source_pages_reconcile_all_connectors_and_safe_outcomes(
    source_schema: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
    uptime: float,
) -> None:
    monkeypatch.setattr(
        "onyx.utils.fleet_telemetry_collector.time",
        SimpleNamespace(monotonic=lambda: uptime, time=time.time),
    )
    source_url, schema = source_schema
    sender = make_sender(capacity=_CAPACITY)
    collector = FleetCollector(sender, source_url, [schema])
    try:
        collector.collect_one_schema()
        collector.collect_one_schema()
        assert not collector.collect_one_schema()
        events = sender._take_batch() + sender._take_batch() + sender._take_batch()
        connectors = [event for event in events if event["event_type"] == "connector"]
        assert len(connectors) == 250
        assert len({event["data"]["cc_pair_id"] for event in connectors}) == 250
        serialized = str(events)
        assert "PRIVATE" not in serialized
        license = next(event for event in events if event["event_type"] == "license")
        assert license["data"]["license_present"] is True
        attempt = next(event for event in events if event["event_type"] == "attempt")
        assert attempt["data"]["state"] == "failed"
        assert attempt["data"]["error_code"] == "auth"
        assert attempt["data"]["error_count"] == 1
        assert attempt["revision"] == 1
        jobs = [event for event in events if event["event_type"] == "job"]
        assert all(event["data"]["cc_pair_id"] == 1 for event in jobs)
        assert {event["data"]["job_type"] for event in jobs} == {
            "permission_sync",
            "group_sync",
        }
        assert (
            next(event for event in jobs if event["data"]["job_type"] == "group_sync")[
                "data"
            ]["memberships_synced"]
            == 7
        )
    finally:
        collector.engine.dispose()


def test_source_engine_cannot_write_and_schema_injection_is_rejected(
    source_schema: tuple[str, str],
) -> None:
    source_url, schema = source_schema
    engine = collector_engine(source_url)
    try:
        with engine.connect() as connection:
            with pytest.raises(InternalError):
                connection.execute(
                    text(f"UPDATE \"{schema}\".connector SET name='PRIVATE'")
                )
        with pytest.raises(ValueError):
            connector_page(engine, "public; DROP SCHEMA public")
        rows = job_page(engine, schema, datetime.now(timezone.utc) - timedelta(days=1))
        assert len(rows) == 2
        active = active_job_page(engine, schema)
        assert len(active) == 1
        assert active[0]["docs_processed"] == 3
        assert active[0]["started_at"] < datetime.now(timezone.utc) - timedelta(days=89)
    finally:
        engine.dispose()


def test_sync_canceled_by_a_new_run_is_read_at_the_live_edge(
    source_schema: tuple[str, str],
) -> None:
    source_url, schema = source_schema
    writer = create_engine(
        source_url, execution_options={"schema_translate_map": {None: schema}}
    )
    # A run that a stopped worker left in progress, older than the repair sweep.
    with writer.begin() as connection:
        stale_id: int = connection.execute(
            text(f"""INSERT INTO "{schema}".sync_record
          (entity_id,sync_type,sync_status,num_docs_synced,sync_start_time)
          VALUES (7,'DOCUMENT_SET','IN_PROGRESS',0,now()-interval '3 days')
          RETURNING id""")
        ).scalar_one()
    with Session(writer) as db_session:
        insert_sync_record(db_session, 7, SyncType.DOCUMENT_SET)
    reader = collector_engine(source_url)
    try:
        rows = job_page(
            reader, schema, datetime.now(timezone.utc) - timedelta(minutes=10)
        )
        by_id = {row["id"]: row for row in rows}
        canceled = by_id.pop(f"sync:{stale_id}")
        assert canceled["state"] == "canceled"
        assert canceled["ended_at"] is not None
        # The new run is read too.
        assert [
            row["state"] for row in by_id.values() if row["job_type"] == "document_set"
        ] == ["in_progress"]
    finally:
        reader.dispose()
        writer.dispose()


def test_domain_view_exposes_only_domains_and_signup_times(
    source_schema: tuple[str, str],
) -> None:
    source_url, schema = source_schema
    engine = collector_engine(source_url)
    try:
        domains = email_domain_page(engine, schema)
        assert domains[0]["domain"] == "onyx.app"
        next_page = email_domain_page(engine, schema, domains[0]["domain"])
        assert next_page[0]["domain"] == "poc.example.com"
        assert next_page[0]["first_signup_at"].year == 2020
        assert set(next_page[0]) == {"domain", "first_signup_at"}
        assert "PRIVATE" not in str(domains + next_page)
        sender = make_sender(capacity=_CAPACITY)
        collector = FleetCollector(sender, source_url, [schema])
        try:
            assert collector.collect_email_domains(schema, 0)
            assert {e["data"]["domain"] for e in sender._take_batch()} == {
                "poc.example.com",
                "onyx.app",
            }
        finally:
            collector.engine.dispose()
    finally:
        engine.dispose()


def test_stage_summaries_page_by_update_and_reconcile_without_source_payloads(
    source_schema: tuple[str, str],
) -> None:
    source_url, schema = source_schema
    engine = create_engine(source_url)
    with engine.begin() as connection:
        connection.execute(
            text(f'''INSERT INTO "{schema}".index_attempt
          (id,connector_credential_pair_id,from_beginning,status)
          SELECT 1000+n,1,true,'IN_PROGRESS' FROM generate_series(1,210) n''')
        )
        connection.execute(
            text(f'''INSERT INTO "{schema}".index_attempt_stage_metric
          (id,index_attempt_id,stage,event_count,total_duration_ms,m2_duration_ms,min_duration_ms,max_duration_ms,time_first_event,time_last_event)
          SELECT n,1000+n,'EMBEDDING',10,10000,500000,100,1500,now()-interval '2 minutes',now()
          FROM generate_series(1,210) n''')
        )
    sender = make_sender(capacity=_CAPACITY)
    collector = FleetCollector(sender, source_url, [schema])
    try:
        collector.collect_stages(schema, 0)
        assert collector._stage_cursor[schema][1] == 200
        collector.collect_stages(schema, 1)
        assert collector._stage_cursor[schema][1] == 0
        events = []
        while batch := sender._take_batch():
            events.extend(batch)
        assert len(events) == 210
        assert {event["data"]["attempt_id"] for event in events} == set(
            range(1001, 1211)
        )
        assert all(event["event_type"] == "stage" for event in events)
        assert all(
            event["data"]["connector_type"] == "google_drive" for event in events
        )
        assert all(
            event["data"]["last_event_at"] == event["occurred_at"] for event in events
        )
        assert "PRIVATE" not in json.dumps(events)
        assert collector.stage_errors == 0
        collector.collect_stages(schema, 2)
        assert not sender._take_batch()
        # Overlap deliberately replays identical IDs; source totals never become deltas.
        collector.collect_stages(schema, 301)
        repeated = sender._take_batch()
        assert repeated[0]["event_id"] == events[0]["event_id"]
    finally:
        collector.engine.dispose()
        engine.dispose()


def test_automatic_identity_is_persistent_and_race_safe(
    source_schema: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from concurrent.futures import ThreadPoolExecutor

    from onyx.db import fleet_enrollment
    from onyx.utils.fleet_telemetry import automatic_config

    url, schema = source_schema
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text(
                f'CREATE TABLE "{schema}".encrypted_key_value_store '
                "(LIKE public.encrypted_key_value_store INCLUDING ALL)"
            )
        )
    monkeypatch.setattr(fleet_enrollment, "POSTGRES_DEFAULT_SCHEMA", schema)
    monkeypatch.setattr(fleet_enrollment, "build_connection_string", lambda **_: url)
    # Application processes select their edition at startup, before enrollment.
    monkeypatch.setattr(fleet_enrollment, "edition_selected", lambda: True)
    with ThreadPoolExecutor(max_workers=4) as workers:
        seeds = list(
            workers.map(lambda _: fleet_enrollment.installation_seed(), range(4))
        )
    assert len(set(seeds)) == 1
    assert fleet_enrollment.installation_seed() == seeds[0]
    first = automatic_config("api", seeds[0])
    restarted = automatic_config("collector", seeds[0])
    assert first and restarted
    assert first.customer_uuid == restarted.customer_uuid
    assert first.token == restarted.token
    assert first.token != first.privacy_key.decode()
    engine.dispose()
