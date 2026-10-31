"""Migration 8673a2d95b1e: token_rate_limit carries its group on the row. A
limit linked to two groups becomes one row per group, an unlinked group limit
is deleted, colliding enabled rows merge, and the downgrade restores the link
table from the rows."""

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

PREVIOUS_REVISION = "17798d4e2385"
KINDS_REVISION = "8673a2d95b1e"
GROUP_NAMES = ("kinds-migration-a", "kinds-migration-b")


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


def _insert_group(engine: Engine, name: str) -> int:
    with engine.begin() as conn:
        return conn.execute(
            text(
                "INSERT INTO user_group (name, is_up_to_date, is_up_for_deletion) "
                "VALUES (:name, true, false) RETURNING id"
            ),
            {"name": name},
        ).scalar_one()


def _insert_limit(
    engine: Engine,
    scope: str,
    token_budget: int,
    group_ids: list[int] | None = None,
) -> int:
    with engine.begin() as conn:
        limit_id = conn.execute(
            text(
                "INSERT INTO token_rate_limit "
                "(enabled, token_budget, period, scope) "
                "VALUES (true, :token_budget, 'DAILY', :scope) RETURNING id"
            ),
            {"token_budget": token_budget, "scope": scope},
        ).scalar_one()
        for group_id in group_ids or []:
            conn.execute(
                text(
                    "INSERT INTO token_rate_limit__user_group "
                    "(rate_limit_id, user_group_id) VALUES (:limit_id, :group_id)"
                ),
                {"limit_id": limit_id, "group_id": group_id},
            )
    return limit_id


def _limit_rows(engine: Engine) -> list[tuple[int, str, int | None, int]]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT id, scope, user_group_id, token_budget "
                "FROM token_rate_limit ORDER BY id"
            )
        ).all()
    return [(row[0], row[1], row[2], row[3]) for row in rows]


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
            conn.execute(text("DELETE FROM token_rate_limit"))
            conn.execute(
                text("DELETE FROM user_group WHERE name = ANY(:names)"),
                {"names": list(GROUP_NAMES)},
            )
        engine.dispose()


def test_group_on_row_merge_and_downgrade(engine: Engine) -> None:
    group_a, group_b = (_insert_group(engine, name) for name in GROUP_NAMES)
    shared = _insert_limit(engine, "USER_GROUP", 50, group_ids=[group_a, group_b])
    _insert_limit(engine, "USER_GROUP", 70)
    first_global = _insert_limit(engine, "GLOBAL", 300)
    _insert_limit(engine, "GLOBAL", 200)

    upgrade_postgres(
        database="postgres", config_name="alembic", revision=KINDS_REVISION
    )

    rows = _limit_rows(engine)
    assert (shared, "USER_GROUP", group_a, 50) in rows
    assert any(
        scope == "USER_GROUP" and group_id == group_b and budget == 50
        for _, scope, group_id, budget in rows
    )
    assert (first_global, "GLOBAL", None, 200) in rows
    assert len(rows) == 3

    downgrade_postgres(
        database="postgres", config_name="alembic", revision=PREVIOUS_REVISION
    )
    with engine.connect() as conn:
        links = set(
            conn.execute(
                text(
                    "SELECT rate_limit_id, user_group_id "
                    "FROM token_rate_limit__user_group"
                )
            ).tuples()
        )
    assert (shared, group_a) in links
    assert len(links) == 2
