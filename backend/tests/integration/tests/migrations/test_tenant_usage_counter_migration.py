"""Migration db8e1bfe4729: tenant_usage_counter replaces tenant_usage. Every
non-zero amount in tenant_usage becomes one calendar row that ends where the
server's calendar period ends. tenant_usage itself is left as it was."""

from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import Engine, create_engine, text

from onyx.configs.app_configs import (
    POSTGRES_HOST,
    POSTGRES_PASSWORD,
    POSTGRES_PORT,
    POSTGRES_USER,
)
from onyx.db.engine.sql_engine import SYNC_DB_API, build_connection_string
from onyx.db.usage import current_calendar_period
from tests.integration.common_utils.reset import downgrade_postgres, upgrade_postgres

PREVIOUS_REVISION = "651681a57efa"
COUNTER_REVISION = "db8e1bfe4729"

LAST_WEEK = datetime(2026, 11, 16, tzinfo=timezone.utc)
THIS_WEEK = datetime(2026, 11, 23, tzinfo=timezone.utc)
EMPTY_WEEK = datetime(2026, 11, 9, tzinfo=timezone.utc)
LAST_WEEK_UPDATED = datetime(2026, 11, 20, 10, tzinfo=timezone.utc)


def _engine() -> Engine:
    return create_engine(
        build_connection_string(
            db="postgres",
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            db_api=SYNC_DB_API,
        )
    )


@pytest.fixture(scope="module")
def engine() -> Generator[Engine, None, None]:
    downgrade_postgres(
        database="postgres", config_name="alembic", revision="base", clear_data=True
    )
    upgrade_postgres(
        database="postgres", config_name="alembic", revision=PREVIOUS_REVISION
    )
    engine = _engine()
    try:
        yield engine
    finally:
        upgrade_postgres(database="postgres", config_name="alembic", revision="head")
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM tenant_usage_counter"))
            conn.execute(text("DELETE FROM tenant_usage"))
        engine.dispose()


def _insert_week(
    engine: Engine,
    window_start: datetime,
    llm_cost_cents: float,
    chunks_indexed: int,
    api_calls: int,
    updated_at: datetime | None,
) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO tenant_usage (window_start, llm_cost_cents, "
                "chunks_indexed, api_calls, non_streaming_api_calls, updated_at) "
                "VALUES (:start, :cost, :chunks, :calls, 0, :updated_at)"
            ),
            {
                "start": window_start,
                "cost": llm_cost_cents,
                "chunks": chunks_indexed,
                "calls": api_calls,
                "updated_at": updated_at,
            },
        )


def _counters(
    engine: Engine,
) -> dict[tuple[str, datetime], tuple[str, datetime, Decimal, datetime]]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT usage_type, window_start, window_anchor, window_end, "
                "amount, updated_at FROM tenant_usage_counter"
            )
        ).all()
    return {(row[0], row[1]): (row[2], row[3], row[4], row[5]) for row in rows}


def test_copies_each_non_zero_amount_into_a_calendar_row(engine: Engine) -> None:
    # The float column drifts: 10,000 adds of 0.01 read back like this.
    _insert_week(engine, LAST_WEEK, 100.00000000001425, 0, 3, LAST_WEEK_UPDATED)
    _insert_week(engine, THIS_WEEK, 1840.5, 210_000, 0, None)
    _insert_week(engine, EMPTY_WEEK, 0, 0, 0, None)

    upgrade_postgres(
        database="postgres", config_name="alembic", revision=COUNTER_REVISION
    )

    # The ends match the periods the server reads.
    last_week_end = current_calendar_period(LAST_WEEK).end
    this_week_end = current_calendar_period(THIS_WEEK).end
    assert _counters(engine) == {
        ("llm_cost_cents", LAST_WEEK): (
            "calendar",
            last_week_end,
            Decimal("100.000000"),
            LAST_WEEK_UPDATED,
        ),
        ("api_calls", LAST_WEEK): (
            "calendar",
            last_week_end,
            Decimal("3.000000"),
            LAST_WEEK_UPDATED,
        ),
        ("llm_cost_cents", THIS_WEEK): (
            "calendar",
            this_week_end,
            Decimal("1840.500000"),
            THIS_WEEK,
        ),
        ("chunks_indexed", THIS_WEEK): (
            "calendar",
            this_week_end,
            Decimal("210000.000000"),
            THIS_WEEK,
        ),
    }
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM tenant_usage")) == 3

    # A rollback drops the new table and keeps the old one.
    downgrade_postgres(
        database="postgres", config_name="alembic", revision=PREVIOUS_REVISION
    )
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT to_regclass('tenant_usage_counter')")) is None
        assert conn.scalar(text("SELECT count(*) FROM tenant_usage")) == 3


def test_copied_rows_end_with_the_configured_period(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With a one-day period, the copied row ends one day after it starts, so
    the server, which reads one-day periods, still sees the usage."""
    one_day = 86400
    downgrade_postgres(
        database="postgres", config_name="alembic", revision=PREVIOUS_REVISION
    )
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM tenant_usage"))
    _insert_week(engine, THIS_WEEK, 50, 0, 0, None)

    # The setting a deployment would change. The migration reads it when it runs.
    monkeypatch.setattr("shared_configs.configs.USAGE_LIMIT_WINDOW_SECONDS", one_day)
    monkeypatch.setattr("onyx.db.usage.USAGE_LIMIT_WINDOW_SECONDS", one_day)
    upgrade_postgres(
        database="postgres", config_name="alembic", revision=COUNTER_REVISION
    )
    server_period = current_calendar_period(THIS_WEEK)

    assert server_period.end == THIS_WEEK + timedelta(days=1)
    assert _counters(engine)[("llm_cost_cents", THIS_WEEK)][1] == server_period.end
