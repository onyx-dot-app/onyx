"""Migration 17798d4e2385: token_rate_limit.period_hours becomes a calendar
period. Each row moves to the closest standard period at least as long as its
own, periods over 30 days prorate their budgets, and enabled rows that collide
on (scope, group set, period) merge, keeping the smaller budgets."""

from collections.abc import Generator

import pytest
from sqlalchemy import Engine, create_engine, text

from onyx.configs.app_configs import (
    POSTGRES_HOST,
    POSTGRES_PASSWORD,
    POSTGRES_PORT,
    POSTGRES_USER,
)
from onyx.db.engine.sql_engine import SYNC_DB_API, build_connection_string
from tests.integration.common_utils.reset import downgrade_postgres, upgrade_postgres

PREVIOUS_REVISION = "1a72785a4e97"
PERIOD_REVISION = "17798d4e2385"
GROUP_NAME = "period-migration-group"
OTHER_GROUP_NAME = "period-migration-other-group"


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


def _insert_limit(
    engine: Engine,
    scope: str,
    period_hours: int,
    token_budget: int | None = None,
    cost_budget_cents: float | None = None,
    enabled: bool = True,
    group_ids: tuple[int, ...] = (),
) -> int:
    with engine.begin() as conn:
        limit_id = conn.execute(
            text(
                "INSERT INTO token_rate_limit "
                "(enabled, token_budget, cost_budget_cents, period_hours, scope) "
                "VALUES (:enabled, :token_budget, :cost, :period_hours, :scope) "
                "RETURNING id"
            ),
            {
                "enabled": enabled,
                "token_budget": token_budget,
                "cost": cost_budget_cents,
                "period_hours": period_hours,
                "scope": scope,
            },
        ).scalar_one()
        for group_id in group_ids:
            conn.execute(
                text(
                    "INSERT INTO token_rate_limit__user_group "
                    "(rate_limit_id, user_group_id) VALUES (:limit_id, :group_id)"
                ),
                {"limit_id": limit_id, "group_id": group_id},
            )
    return limit_id


def _insert_group(engine: Engine, name: str) -> int:
    with engine.begin() as conn:
        return conn.execute(
            text(
                "INSERT INTO user_group (name, is_up_to_date, is_up_for_deletion) "
                "VALUES (:name, true, false) RETURNING id"
            ),
            {"name": name},
        ).scalar_one()


def _linked_group_ids(engine: Engine, limit_id: int) -> set[int]:
    with engine.connect() as conn:
        return set(
            conn.execute(
                text(
                    "SELECT user_group_id FROM token_rate_limit__user_group "
                    "WHERE rate_limit_id = :limit_id"
                ),
                {"limit_id": limit_id},
            ).scalars()
        )


def _limits(engine: Engine) -> dict[int, tuple[str, int | None, float | None]]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT id, period, token_budget, cost_budget_cents "
                "FROM token_rate_limit"
            )
        ).all()
    return {row[0]: (row[1], row[2], row[3]) for row in rows}


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
            conn.execute(text("DELETE FROM token_rate_limit__user_group"))
            conn.execute(text("DELETE FROM token_rate_limit"))
            conn.execute(
                text("DELETE FROM user_group WHERE name = ANY(:names)"),
                {"names": [GROUP_NAME, OTHER_GROUP_NAME]},
            )
        engine.dispose()


def test_period_mapping_proration_and_merge(engine: Engine) -> None:
    group_id = _insert_group(engine, GROUP_NAME)
    other_group_id = _insert_group(engine, OTHER_GROUP_NAME)

    daily = _insert_limit(engine, "GLOBAL", 24, token_budget=10)
    monthly = _insert_limit(engine, "GLOBAL", 720, cost_budget_cents=500)
    # 14 days -> MONTHLY, 45 days -> MONTHLY prorated by 30/45; distinct scopes
    # keep them from colliding with the global monthly row.
    two_weeks = _insert_limit(engine, "USER", 336, token_budget=50)
    long_period = _insert_limit(
        engine,
        "USER_GROUP",
        45 * 24,
        token_budget=90,
        cost_budget_cents=900,
        group_ids=(group_id,),
    )
    # Same period and scope, but a different group set: no merge.
    two_groups = _insert_limit(
        engine,
        "USER_GROUP",
        720,
        token_budget=70,
        group_ids=(group_id, other_group_id),
    )
    # token_budget * 30 overflows a 32-bit integer.
    large_budget = _insert_limit(
        engine, "GLOBAL", 45 * 24, token_budget=100_000_000, enabled=False
    )
    # 3 days and 7 days both become WEEKLY for user scope: they merge.
    three_days = _insert_limit(engine, "USER", 72, token_budget=100)
    week = _insert_limit(engine, "USER", 168, token_budget=200, cost_budget_cents=300)
    # Disabled rows never merge.
    disabled_week = _insert_limit(engine, "USER", 168, token_budget=1, enabled=False)

    upgrade_postgres(
        database="postgres", config_name="alembic", revision=PERIOD_REVISION
    )

    limits = _limits(engine)
    assert limits[daily] == ("DAILY", 10, None)
    assert limits[monthly] == ("MONTHLY", None, 500)
    assert limits[two_weeks] == ("MONTHLY", 50, None)
    assert limits[long_period] == ("MONTHLY", 60, 600)
    assert limits[two_groups] == ("MONTHLY", 70, None)
    assert _linked_group_ids(engine, long_period) == {group_id}
    assert _linked_group_ids(engine, two_groups) == {group_id, other_group_id}
    assert limits[large_budget] == ("MONTHLY", 66_666_666, None)
    assert limits[three_days] == ("WEEKLY", 100, 300)
    assert week not in limits
    assert limits[disabled_week] == ("WEEKLY", 1, None)

    downgrade_postgres(
        database="postgres", config_name="alembic", revision=PREVIOUS_REVISION
    )
    with engine.connect() as conn:
        hours: dict[int, int] = {
            row[0]: row[1]
            for row in conn.execute(
                text("SELECT id, period_hours FROM token_rate_limit")
            ).all()
        }
    assert hours[daily] == 24
    assert hours[three_days] == 168
    assert hours[long_period] == 720

    upgrade_postgres(database="postgres", config_name="alembic", revision="head")
    assert _limits(engine)[three_days] == ("WEEKLY", 100, 300)
