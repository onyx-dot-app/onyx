"""Read-only, bounded reconciliation queries for the isolated telemetry collector."""

import os
import re
from datetime import datetime
from typing import Any

from sqlalchemy import Connection, Engine, create_engine, event, text

SAFE_BOOLEAN_SETTINGS = (
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
SAFE_NUMBER_SETTINGS = (
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
_SCOPE_ARRAYS = (
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


def collector_engine(database_url: str) -> Engine:
    if not database_url.startswith(("postgresql://", "postgresql+psycopg2://")):
        raise ValueError("The collector requires PostgreSQL")
    engine = create_engine(
        database_url,
        pool_size=1,
        max_overflow=0,
        pool_timeout=0.2,
        pool_pre_ping=False,
        connect_args={
            "connect_timeout": 2,
            "application_name": "onyx_fleet_collector",
        },
    )

    if not os.environ.get("ONYX_TELEMETRY_DATABASE_URL"):
        from onyx.configs.app_configs import USE_IAM_AUTH
        from onyx.db.engine.iam_auth import provide_iam_token

        if USE_IAM_AUTH:
            event.listen(engine, "do_connect", provide_iam_token)

    @event.listens_for(engine, "begin")
    def _read_limits(connection: Connection) -> None:
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        connection.exec_driver_sql("SET LOCAL statement_timeout = '1500ms'")
        connection.exec_driver_sql("SET LOCAL lock_timeout = '100ms'")

    return engine


def _schema(schema: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]{0,62}", schema):
        raise ValueError("Invalid collector schema")
    return '"' + schema + '"'


def _safe_configuration_expression() -> str:
    # PostgreSQL returns only reviewed scalars/counts. Names, credentials, paths,
    # URLs, and raw configuration JSON never leave the database connection.
    config = "c.connector_specific_config"
    entries = [
        f"'{key}',CASE WHEN jsonb_typeof({config}->'{key}')='boolean' THEN {config}->'{key}' END"
        for key in SAFE_BOOLEAN_SETTINGS
    ]
    entries.extend(
        f"'{key}',CASE WHEN jsonb_typeof({config}->'{key}')='number' THEN {config}->'{key}' END"
        for key in SAFE_NUMBER_SETTINGS
    )
    counts = " + ".join(
        f"CASE WHEN jsonb_typeof({config}->'{key}')='array' THEN jsonb_array_length({config}->'{key}') ELSE 0 END"
        for key in _SCOPE_ARRAYS
    )
    entries.append("'selection_count'," + counts)
    for output, key in {
        "include_rule_count": "include_rules",
        "exclude_rule_count": "exclude_rules",
        "include_pattern_count": "include_patterns",
        "exclude_pattern_count": "exclude_patterns",
        "file_type_count": "file_types",
    }.items():
        entries.append(
            f"'{output}',CASE WHEN jsonb_typeof({config}->'{key}')='array' THEN jsonb_array_length({config}->'{key}') ELSE 0 END"
        )
    entries.append(
        f"'has_time_filter',({config} ? 'start_date' OR {config} ? 'time_range' OR {config} ? 'start_time')"
    )
    return "jsonb_strip_nulls(jsonb_build_object(" + ",".join(entries) + "))"


def connector_page(
    engine: Engine, schema: str, after_id: int = 0, limit: int = 200
) -> list[dict[str, Any]]:
    scoped = _schema(schema)
    statement = f"""
        SELECT p.id AS cc_pair_id, c.id AS connector_id, c.source AS connector_type,
          lower(p.status) AS state, p.total_docs_indexed AS doc_count,
          p.last_successful_index_time AS last_success_at,
          c.time_updated, c.refresh_freq AS refresh_seconds, c.prune_freq AS prune_seconds,
          (p.auto_sync_options IS NOT NULL) AS auto_sync_enabled,
          (p.access_type = 'SYNC') AS permission_sync_enabled,
          {_safe_configuration_expression()} AS metadata
        FROM {scoped}.connector_credential_pair p
        JOIN {scoped}.connector c ON c.id=p.connector_id
        WHERE p.id > :after_id AND p.id > 0 ORDER BY p.id LIMIT :limit
    """  # noqa: S608 - Schema is strictly validated; values are bound.
    with engine.connect() as connection:
        return [
            dict(row)
            for row in connection.execute(
                text(statement),
                {"after_id": after_id, "limit": min(500, max(1, limit))},
            ).mappings()
        ]


def attempt_page(
    engine: Engine, schema: str, since: datetime, after_id: int = 0, limit: int = 200
) -> list[dict[str, Any]]:
    scoped = _schema(schema)
    statement = f"""
        SELECT a.id AS attempt_id, p.id AS cc_pair_id, c.id AS connector_id,
          c.source AS connector_type, lower(a.status) AS state,
          a.total_docs_indexed AS docs_indexed, a.total_docs_indexed AS docs_processed,
          a.total_chunks AS chunks_indexed, a.total_batches, a.completed_batches,
          a.time_started AS started_at, a.time_updated,
          a.last_progress_time AS last_progress_at, a.last_heartbeat_time AS last_heartbeat_at,
          (a.error_msg IS NOT NULL) AS has_error,
          left(a.error_msg,2048) AS local_error_sample,
          (SELECT left(e.error_type,128) FROM {scoped}.index_attempt_errors e
           WHERE e.index_attempt_id=a.id AND NOT e.is_resolved
           ORDER BY e.id DESC LIMIT 1) AS local_error_type,
          (SELECT left(e.failure_message,2048) FROM {scoped}.index_attempt_errors e
           WHERE e.index_attempt_id=a.id AND NOT e.is_resolved
           ORDER BY e.id DESC LIMIT 1) AS local_item_error_sample,
          (SELECT COUNT(*) FROM {scoped}.index_attempt_errors e
           WHERE e.index_attempt_id=a.id AND NOT e.is_resolved) AS error_count
        FROM {scoped}.index_attempt a
        JOIN {scoped}.connector_credential_pair p ON p.id=a.connector_credential_pair_id
        JOIN {scoped}.connector c ON c.id=p.connector_id
        WHERE (a.time_updated, a.id) > (:since, :after_id)
          AND NOT a.is_synthetic_seed
        ORDER BY a.time_updated, a.id LIMIT :limit
    """  # noqa: S608 - Schema is strictly validated; values are bound.
    with engine.connect() as connection:
        return [
            dict(row)
            for row in connection.execute(
                text(statement),
                {
                    "since": since,
                    "after_id": after_id,
                    "limit": min(500, max(1, limit)),
                },
            ).mappings()
        ]


def job_page(
    engine: Engine,
    schema: str,
    since: datetime,
    after_id: str = "",
    limit: int = 200,
    *,
    active_only: bool = False,
) -> list[dict[str, Any]]:
    scoped = _schema(schema)
    selection = (
        "state IN ('not_started','in_progress','scheduled') AND id > :after_id"
        if active_only
        else "(revision_at,id) > (:since,:after_id)"
    )
    ordering = "id" if active_only else "revision_at,id"
    statement = f"""
        SELECT * FROM (
          SELECT 'sync:' || id::text AS id, entity_id, lower(sync_type) AS job_type,
            lower(sync_status) AS state, num_docs_synced AS docs_processed,
            0 AS users_processed, 0 AS groups_processed, 0 AS memberships_synced,
            0 AS error_count, sync_start_time AS started_at, sync_end_time AS ended_at,
            COALESCE(sync_end_time,sync_start_time) AS revision_at
          FROM {scoped}.sync_record
          UNION ALL
          SELECT 'permission:' || id::text, connector_credential_pair_id, 'permission_sync',
            lower(status), total_docs_synced, 0, 0, 0,
            docs_with_permission_errors, time_started, time_finished,
            COALESCE(time_finished,time_started,time_created)
          FROM {scoped}.doc_permission_sync_attempt
          UNION ALL
          SELECT 'group:' || id::text, connector_credential_pair_id, 'group_sync',
            lower(status), 0, total_users_processed, total_groups_processed,
            total_group_memberships_synced, (error_message IS NOT NULL)::integer,
            time_started,time_finished,COALESCE(time_finished,time_started,time_created)
          FROM {scoped}.external_group_permission_sync_attempt
          UNION ALL
          SELECT 'hierarchy:' || id::text, connector_credential_pair_id, 'hierarchy',
            lower(status), 0, 0, 0, 0, (error_msg IS NOT NULL)::integer,
            time_started, CASE WHEN lower(status) IN ('success','failed','canceled','interrupted','completed_with_errors') THEN time_updated END,
            time_updated
          FROM {scoped}.hierarchy_fetch_attempt
          UNION ALL
          SELECT 'port:' || id::text, cc_pair_id, 'migration', lower(status), docs_ported,
            0,0,0,(error_msg IS NOT NULL)::integer,time_started,time_completed,time_updated
          FROM {scoped}.port_attempt
        ) jobs
        WHERE {selection}
        ORDER BY {ordering} LIMIT :limit
    """  # noqa: S608 - Schema is strictly validated; values are bound.
    with engine.connect() as connection:
        return [
            dict(row)
            for row in connection.execute(
                text(statement),
                {
                    "since": since,
                    "after_id": str(after_id) if after_id else "",
                    "limit": min(500, max(1, limit)),
                },
            ).mappings()
        ]


def email_domain_page(
    engine: Engine, schema: str, after_domain: str = "", limit: int = 200
) -> list[dict[str, Any]]:
    scoped = _schema(schema)
    statement = f"""SELECT domain,first_signup_at FROM {scoped}.fleet_signup_email_domains
        WHERE domain > :after_domain ORDER BY domain LIMIT :limit"""  # noqa: S608 - Validated schema and bound values.
    with engine.connect() as connection:
        return [
            dict(row)
            for row in connection.execute(
                text(statement),
                {"after_domain": after_domain, "limit": min(200, max(1, limit))},
            ).mappings()
        ]


def license_snapshot(engine: Engine, schema: str) -> dict[str, Any]:
    scoped = _schema(schema)
    statement = f"SELECT license_present,first_set_at FROM {scoped}.fleet_license_state"  # noqa: S608 - Validated schema.
    with engine.connect() as connection:
        return dict(connection.execute(text(statement)).mappings().one())


def tenant_schemas(engine: Engine) -> list[str]:
    with engine.connect() as connection:
        return list(
            connection.execute(
                text(
                    "SELECT nspname FROM pg_namespace WHERE nspname LIKE 'tenant\\_%' ESCAPE '\\' ORDER BY nspname LIMIT 10000"
                )
            ).scalars()
        )


def stage_metric_page(
    engine: Engine, schema: str, since: datetime, after_id: int = 0, limit: int = 200
) -> list[dict[str, Any]]:
    """Read changed numeric stage summaries using the timestamp/id index."""
    scoped = _schema(schema)
    statement = f"""
        SELECT m.id, m.index_attempt_id AS attempt_id, m.stage, m.event_count,
          m.total_duration_ms, m.min_duration_ms, m.max_duration_ms,
          m.m2_duration_ms, m.time_first_event AS first_event_at,
          m.time_last_event AS last_event_at,
          a.connector_credential_pair_id AS cc_pair_id,
          p.connector_id, c.source AS connector_type
        FROM {scoped}.index_attempt_stage_metric m
        JOIN {scoped}.index_attempt a ON a.id=m.index_attempt_id
        JOIN {scoped}.connector_credential_pair p ON p.id=a.connector_credential_pair_id
        JOIN {scoped}.connector c ON c.id=p.connector_id
        WHERE (m.time_last_event,m.id) > (:since,:after_id)
          AND m.time_last_event > now()-interval '30 days' AND NOT a.is_synthetic_seed
        ORDER BY m.time_last_event,m.id LIMIT :limit
    """  # noqa: S608 - Validated schema; all cursor values are bound.
    with engine.connect() as connection:
        return [
            dict(row)
            for row in connection.execute(
                text(statement),
                {
                    "since": since,
                    "after_id": after_id,
                    "limit": min(200, max(1, limit)),
                },
            ).mappings()
        ]
