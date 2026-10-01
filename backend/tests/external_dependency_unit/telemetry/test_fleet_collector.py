"""Run against a migrated local source DB and a live telemetry HTTP endpoint."""

import json
import os
import uuid
from collections.abc import Generator
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import InternalError

from onyx.db.fleet_telemetry import collector_engine, connector_page, job_page
from onyx.utils.fleet_telemetry import BoundedTelemetry, TelemetryConfig
from onyx.utils.fleet_telemetry_collector import FleetCollector


@pytest.fixture
def source_schema() -> Generator[tuple[str, str], None, None]:
    source_url = os.environ["ONYX_TELEMETRY_TEST_DB"]
    schema = "telemetry_test_" + uuid.uuid4().hex[:12]
    engine = create_engine(source_url)
    tables = (
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
        for number in range(1, 251):
            connection.execute(
                text(f"""INSERT INTO "{schema}".connector
              (id,name,source,input_type,connector_specific_config,kg_processing_enabled,refresh_freq)
              VALUES (:id,'PRIVATE CONNECTOR','GOOGLE_DRIVE','LOAD_STATE',
              CAST(:config AS jsonb),false,600)"""),
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


def test_bounded_source_pages_reconcile_all_connectors_and_safe_outcomes(
    source_schema: tuple[str, str],
) -> None:
    source_url, schema = source_schema
    sender = _sender()
    collector = FleetCollector(sender, source_url, [schema])
    try:
        collector.collect_one_schema()
        collector.collect_one_schema()
        events = sender._take_batch() + sender._take_batch() + sender._take_batch()
        connectors = [event for event in events if event["event_type"] == "connector"]
        assert len(connectors) == 250
        assert len({event["data"]["cc_pair_id"] for event in connectors}) == 250
        serialized = str(events)
        assert "PRIVATE" not in serialized
        attempt = next(event for event in events if event["event_type"] == "attempt")
        assert attempt["data"]["state"] == "failed"
        assert attempt["data"]["error_code"] == "auth"
        jobs = [event for event in events if event["event_type"] == "job"]
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
