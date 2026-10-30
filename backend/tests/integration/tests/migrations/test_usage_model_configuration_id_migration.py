"""Migrations 0437efc9ed01 and 1a72785a4e97: user_usage records the model
configuration id, the current month is backfilled where (model, provider) names
exactly one configuration, and the dedup indexes key on the id. The downgrade
folds rows that differ only by id back into one."""

from collections.abc import Generator
from datetime import datetime, timedelta, timezone

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

PREVIOUS_REVISION = "b7d2e4f1a9c3"
INDEX_REVISION = "1a72785a4e97"


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


def _current_month_start() -> datetime:
    return datetime.now(timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )


def _insert_provider(engine: Engine, name: str, provider: str) -> int:
    with engine.begin() as conn:
        return conn.execute(
            text(
                "INSERT INTO llm_provider (name, provider) VALUES (:name, :provider) "
                "RETURNING id"
            ),
            {"name": name, "provider": provider},
        ).scalar_one()


def _insert_model(engine: Engine, provider_id: int, name: str) -> int:
    with engine.begin() as conn:
        return conn.execute(
            text(
                "INSERT INTO model_configuration (llm_provider_id, name, is_visible) "
                "VALUES (:provider_id, :name, true) RETURNING id"
            ),
            {"provider_id": provider_id, "name": name},
        ).scalar_one()


def _insert_usage(
    engine: Engine,
    model: str,
    provider: str,
    window_start: datetime,
    tokens: int,
    model_configuration_id: int | None = None,
) -> int:
    columns = "window_start, model, flow, provider, input_tokens, output_tokens"
    values = ":window_start, :model, 'CHAT', :provider, :tokens, 0"
    params: dict[str, object] = {
        "window_start": window_start,
        "model": model,
        "provider": provider,
        "tokens": tokens,
    }
    if model_configuration_id is not None:
        columns += ", model_configuration_id"
        values += ", :model_configuration_id"
        params["model_configuration_id"] = model_configuration_id
    with engine.begin() as conn:
        return conn.execute(
            text(f"INSERT INTO user_usage ({columns}) VALUES ({values}) RETURNING id"),
            params,
        ).scalar_one()


def _usage_model_id(engine: Engine, usage_id: int) -> int | None:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT model_configuration_id FROM user_usage WHERE id = :id"),
            {"id": usage_id},
        ).scalar_one()


def _index_defs(engine: Engine) -> list[str]:
    with engine.connect() as conn:
        return list(
            conn.execute(
                text(
                    "SELECT indexdef FROM pg_indexes WHERE tablename = 'user_usage' "
                    "AND indexname IN ('uq_user_usage_dims', 'uq_system_usage_dims')"
                )
            ).scalars()
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
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM user_usage"))
        upgrade_postgres(database="postgres", config_name="alembic", revision="head")
        engine.dispose()


def test_backfill_index_swap_and_downgrade(engine: Engine) -> None:
    unique_provider_id = _insert_provider(engine, "anthropic-main", "anthropic")
    sonnet_id = _insert_model(engine, unique_provider_id, "claude-sonnet")
    # Two openai providers both configure gpt-5: (model, provider) is ambiguous.
    for provider_name in ("openai-a", "openai-b"):
        _insert_model(
            engine, _insert_provider(engine, provider_name, "openai"), "gpt-5"
        )

    month_start = _current_month_start()
    this_month = _insert_usage(engine, "claude-sonnet", "anthropic", month_start, 10)
    last_month = _insert_usage(
        engine, "claude-sonnet", "anthropic", month_start - timedelta(days=1), 10
    )
    ambiguous = _insert_usage(engine, "gpt-5", "openai", month_start, 10)

    upgrade_postgres(
        database="postgres", config_name="alembic", revision=INDEX_REVISION
    )

    assert _usage_model_id(engine, this_month) == sonnet_id
    assert _usage_model_id(engine, last_month) is None
    assert _usage_model_id(engine, ambiguous) is None
    index_defs = _index_defs(engine)
    assert len(index_defs) == 2
    assert all("COALESCE(model_configuration_id, 0)" in d for d in index_defs)

    # A second configuration with the same (model, provider) gets its own row.
    other_sonnet_id = _insert_model(
        engine, _insert_provider(engine, "anthropic-alt", "anthropic"), "claude-sonnet"
    )
    _insert_usage(
        engine,
        "claude-sonnet",
        "anthropic",
        month_start,
        5,
        model_configuration_id=other_sonnet_id,
    )

    downgrade_postgres(
        database="postgres", config_name="alembic", revision=PREVIOUS_REVISION
    )

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT input_tokens FROM user_usage "
                "WHERE model = 'claude-sonnet' AND window_start = :month_start"
            ),
            {"month_start": month_start},
        ).all()
    assert [row[0] for row in rows] == [15]
    assert not any("model_configuration_id" in d for d in _index_defs(engine))

    upgrade_postgres(database="postgres", config_name="alembic", revision="head")
    assert all("COALESCE(model_configuration_id, 0)" in d for d in _index_defs(engine))
