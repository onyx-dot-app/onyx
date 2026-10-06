"""Run against a migrated local source DB and a live telemetry HTTP endpoint."""

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

from onyx.db.engine.sql_engine import SYNC_DB_API, build_connection_string
from onyx.db.fleet_telemetry import (
    collector_engine,
    connector_page,
    email_domain_page,
    job_page,
)
from onyx.utils.fleet_telemetry import BoundedTelemetry, TelemetryConfig
from onyx.utils.fleet_telemetry_collector import FleetCollector


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
        "sync_record",
        "doc_permission_sync_attempt",
        "external_group_permission_sync_attempt",
        "hierarchy_fetch_attempt",
        "port_attempt",
    )
    with engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))  # noqa: S608 - Generated schema uses hex only.
        for table in tables:
            connection.execute(
                text(
                    f'CREATE TABLE "{schema}".{table} (LIKE public.{table} INCLUDING DEFAULTS)'
                )
            )  # noqa: S608 - Fixed table allowlist and generated schema.
        connection.execute(
            text(f'''CREATE TABLE "{schema}"."user" (
            email text,created_at timestamptz,account_type text)''')
        )  # noqa: S608 - Generated schema only.
        connection.execute(
            text(f'''INSERT INTO "{schema}"."user" VALUES
            ('PRIVATE FIRST@Poc.Example.COM','2020-01-01','STANDARD'),
            ('PRIVATE SECOND@onyx.app','2021-01-01','STANDARD'),
            ('PRIVATE THIRD@poc.example.com','2022-01-01','STANDARD'),
            ('PRIVATE BOT@excluded.example.com','2019-01-01','BOT')''')
        )  # noqa: S608 - Generated schema only.
        connection.execute(
            text(f'''CREATE VIEW "{schema}".fleet_signup_email_domains WITH (security_barrier=true) AS
            SELECT lower(split_part(email,'@',2)) AS domain,min(created_at) AS first_signup_at
            FROM "{schema}"."user" WHERE account_type='STANDARD' AND email ~ '^[^@]+@[^@]+$'
            GROUP BY lower(split_part(email,'@',2))''')
        )  # noqa: S608 - Generated schema only.
        connection.execute(
            text(f'INSERT INTO "{schema}".license (license_data) VALUES (:key)'),
            {"key": "PRIVATE LICENSE"},
        )  # noqa: S608 - Generated schema and fixed test fixture.
        connection.execute(
            text(f"""CREATE VIEW "{schema}".fleet_license_state WITH (security_barrier=true) AS
            SELECT coalesce(bool_or(length(license_data)>0),false) AS license_present,
            min(created_at) FILTER (WHERE length(license_data)>0) AS first_set_at
            FROM "{schema}".license""")
        )  # noqa: S608 - Generated schema only.
        # Collection must not depend on obsolete connector columns.
        connection.execute(
            text(
                f'ALTER TABLE "{schema}".connector DROP COLUMN kg_processing_enabled, DROP COLUMN kg_coverage_days'
            )
        )  # noqa: S608 - Generated schema uses hex only.
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
            )  # noqa: S608 - Generated schema only.
            connection.execute(
                text(f"""INSERT INTO "{schema}".connector_credential_pair
              (id,name,status,connector_id,credential_id,access_type,total_docs_indexed)
              VALUES (:id,'PRIVATE CONNECTOR','ACTIVE',:id,123,'PUBLIC',100)"""),
                {"id": number},
            )  # noqa: S608 - Generated schema only.
        connection.execute(
            text(f"""INSERT INTO "{schema}".index_attempt
          (id,connector_credential_pair_id,from_beginning,status,error_msg,new_docs_indexed,total_docs_indexed,total_chunks,total_batches,completed_batches)
          VALUES (1,1,true,'FAILED','401 unauthorized PRIVATE TOKEN PRIVATE FOLDER',10,20,30,4,2)""")
        )  # noqa: S608 - Generated schema only.
        connection.execute(
            text(f"""INSERT INTO "{schema}".doc_permission_sync_attempt
          (id,connector_credential_pair_id,status,total_docs_synced,docs_with_permission_errors,time_started,time_finished)
          VALUES (1,1,'SUCCESS',99,0,now()-interval '5 minutes',now())""")
        )  # noqa: S608 - Generated schema only.
        connection.execute(
            text(f"""INSERT INTO "{schema}".external_group_permission_sync_attempt
          (id,connector_credential_pair_id,status,total_users_processed,total_groups_processed,total_group_memberships_synced,time_started,time_finished)
          VALUES (1,1,'SUCCESS',5,2,7,now()-interval '5 minutes',now())""")
        )  # noqa: S608 - Generated schema only.
        connection.execute(
            text(f"""INSERT INTO "{schema}".doc_permission_sync_attempt
          (id,connector_credential_pair_id,status,total_docs_synced,docs_with_permission_errors,time_started)
          VALUES (2,1,'IN_PROGRESS',3,0,now()-interval '90 days')""")
        )  # noqa: S608 - Generated schema only.
    try:
        yield source_url, schema
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))  # noqa: S608 - Generated test schema only.
        engine.dispose()


def _sender() -> BoundedTelemetry:
    return BoundedTelemetry(
        TelemetryConfig(
            "http://localhost:8787",
            "test",
            "11111111-1111-4111-8111-111111111111",
            "integration-test",
            b"unique-installation-test-privacy-key",
            capacity=1024,
        )
    )


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
    sender = _sender()
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
        assert all("docs_total" not in event["data"] for event in jobs)
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
                )  # noqa: S608 - Generated test schema only.
        with pytest.raises(ValueError):
            connector_page(engine, "public; DROP SCHEMA public")
        rows = job_page(engine, schema, datetime.now(timezone.utc) - timedelta(days=1))
        assert len(rows) == 2
        active = job_page(
            engine,
            schema,
            datetime.now(timezone.utc) - timedelta(days=1),
            active_only=True,
        )
        assert len(active) == 1
        assert active[0]["docs_processed"] == 3
        assert active[0]["started_at"] < datetime.now(timezone.utc) - timedelta(days=89)
    finally:
        engine.dispose()


def test_domain_view_exposes_only_domains_and_signup_times(
    source_schema: tuple[str, str],
) -> None:
    source_url, schema = source_schema
    engine = collector_engine(source_url)
    try:
        domains = email_domain_page(engine, schema, limit=1)
        assert domains[0]["domain"] == "onyx.app"
        next_page = email_domain_page(engine, schema, domains[0]["domain"])
        assert next_page[0]["domain"] == "poc.example.com"
        assert next_page[0]["first_signup_at"].year == 2020
        assert set(next_page[0]) == {"domain", "first_signup_at"}
        assert "PRIVATE" not in str(domains + next_page)
        sender = _sender()
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
