"""Tests for migration d5f9b2a4c3e8, which moves the preference columns of
`user` to the `user_preferences` table. Upgrade copies every user's values and
drops the columns; downgrade copies them back."""

import json
from collections.abc import Generator
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Connection, Engine, create_engine, text

from onyx.configs.app_configs import (
    POSTGRES_DB,
    POSTGRES_HOST,
    POSTGRES_PASSWORD,
    POSTGRES_PORT,
    POSTGRES_USER,
)
from onyx.db.engine.sql_engine import SYNC_DB_API, build_connection_string
from tests.integration.common_utils.reset import downgrade_postgres, upgrade_postgres

REVISION = "d5f9b2a4c3e8"
PREVIOUS_REVISION = f"{REVISION}-1"

# Non-default values for every moved column, keyed by the `user` column name.
CUSTOM_USER_VALUES: dict[str, Any] = {
    "default_model": "Provider__openai__gpt-6-luna",
    "temperature_override_enabled": True,
    "temperature_default": 0.4,
    "reasoning_effort_default": "high",
    "auto_scroll": False,
    "shortcut_enabled": True,
    "theme_preference": "DARK",
    "language": "de",
    "chat_background": "aurora",
    "default_app_mode": "SEARCH",
    "use_memories": False,
    "enable_memory_tool": False,
    "user_preferences": "Answer tersely.",
    "chosen_assistants": [3, 1],
    "visible_assistants": [5],
    "hidden_assistants": [7, 8],
    "paste_as_tile": True,
    "interrupt_on_send": True,
    "voice_auto_send": True,
    "voice_auto_playback": True,
    "voice_playback_speed": 1.5,
}
JSONB_COLUMNS = {"chosen_assistants", "visible_assistants", "hidden_assistants"}

# What a user who never changed a setting has: the column defaults.
DEFAULT_PREFERENCES: dict[str, Any] = {
    "default_model": None,
    "temperature_override_enabled": None,
    "temperature_default": None,
    "reasoning_effort_default": None,
    "auto_scroll": None,
    "shortcut_enabled": False,
    "theme_preference": None,
    "language": None,
    "chat_background": None,
    "default_app_mode": "CHAT",
    "use_memories": True,
    "enable_memory_tool": True,
    "instructions": None,
    "chosen_assistants": None,
    "visible_assistants": [],
    "hidden_assistants": [],
    "paste_as_tile": False,
    "interrupt_on_send": False,
    "voice_auto_send": False,
    "voice_auto_playback": False,
    "voice_playback_speed": 1.0,
}


# The one column whose name changes: `user.user_preferences` holds the
# instructions.
USER_NAME_OF = {"instructions": "user_preferences"}
PREFERENCES_NAME_OF = {"user_preferences": "instructions"}
DEFAULT_USER_VALUES = {
    USER_NAME_OF.get(name, name): value for name, value in DEFAULT_PREFERENCES.items()
}


@pytest.fixture
def engine() -> Generator[Engine, None, None]:
    upgrade_postgres(database=POSTGRES_DB, config_name="alembic", revision="head")
    downgrade_postgres(
        database=POSTGRES_DB, config_name="alembic", revision=PREVIOUS_REVISION
    )
    engine = create_engine(
        build_connection_string(
            db=POSTGRES_DB,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            db_api=SYNC_DB_API,
        )
    )
    try:
        yield engine
    finally:
        upgrade_postgres(database=POSTGRES_DB, config_name="alembic", revision="head")
        engine.dispose()


def _insert_user(conn: Connection, user_id: UUID) -> None:
    conn.execute(
        text(
            'INSERT INTO "user" (id, email, hashed_password, is_active, '
            "is_superuser, is_verified) "
            "VALUES (:id, :email, '', true, false, true)"
        ),
        {"id": user_id, "email": f"prefs-{user_id.hex}@example.com"},
    )


@pytest.fixture
def user_ids(engine: Engine) -> Generator[tuple[UUID, UUID], None, None]:
    """A user with a non-default value in every preference column, and a user
    with the defaults, created on the schema before the revision."""
    custom_id, default_id = uuid4(), uuid4()
    with engine.begin() as conn:
        for user_id in (custom_id, default_id):
            _insert_user(conn, user_id)
        assignments = ", ".join(
            f"{column} = CAST(:{column} AS jsonb)"
            if column in JSONB_COLUMNS
            else f"{column} = :{column}"
            for column in CUSTOM_USER_VALUES
        )
        conn.execute(
            text(f'UPDATE "user" SET {assignments} WHERE id = :id'),
            {
                "id": custom_id,
                **{
                    column: json.dumps(value) if column in JSONB_COLUMNS else value
                    for column, value in CUSTOM_USER_VALUES.items()
                },
            },
        )
    yield custom_id, default_id
    with engine.begin() as conn:
        conn.execute(
            text('DELETE FROM "user" WHERE id IN (:custom_id, :default_id)'),
            {"custom_id": custom_id, "default_id": default_id},
        )


def _preferences_row(engine: Engine, user_id: UUID) -> dict[str, Any]:
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM user_preferences WHERE user_id = :id"),
            {"id": user_id},
        ).one()
    values = dict(row._mapping)
    values.pop("user_id")
    return values


def _user_preference_values(engine: Engine, user_id: UUID) -> dict[str, Any]:
    columns = ", ".join(USER_NAME_OF.get(name, name) for name in DEFAULT_PREFERENCES)
    with engine.connect() as conn:
        row = conn.execute(
            text(f'SELECT {columns} FROM "user" WHERE id = :id'), {"id": user_id}
        ).one()
    return dict(row._mapping)


def _user_columns(engine: Engine) -> set[str]:
    with engine.connect() as conn:
        return set(
            conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = 'user'"
                )
            ).scalars()
        )


def _assert_upgraded(engine: Engine, custom_id: UUID, default_id: UUID) -> None:
    assert _preferences_row(engine, custom_id) == {
        PREFERENCES_NAME_OF.get(column, column): value
        for column, value in CUSTOM_USER_VALUES.items()
    }
    assert _preferences_row(engine, default_id) == DEFAULT_PREFERENCES
    moved = {USER_NAME_OF.get(name, name) for name in DEFAULT_PREFERENCES}
    assert not moved & _user_columns(engine)


def test_upgrade_downgrade_upgrade_keeps_every_value(
    engine: Engine, user_ids: tuple[UUID, UUID]
) -> None:
    custom_id, default_id = user_ids

    upgrade_postgres(database=POSTGRES_DB, config_name="alembic", revision=REVISION)
    _assert_upgraded(engine, custom_id, default_id)

    downgrade_postgres(
        database=POSTGRES_DB, config_name="alembic", revision=PREVIOUS_REVISION
    )
    with engine.connect() as conn:
        assert (
            conn.execute(text("SELECT to_regclass('user_preferences')")).scalar()
            is None
        )
    assert _user_preference_values(engine, custom_id) == CUSTOM_USER_VALUES
    assert _user_preference_values(engine, default_id) == DEFAULT_USER_VALUES

    upgrade_postgres(database=POSTGRES_DB, config_name="alembic", revision=REVISION)
    _assert_upgraded(engine, custom_id, default_id)


def test_downgrade_gives_defaults_to_user_without_preferences_row(
    engine: Engine,
) -> None:
    upgrade_postgres(database=POSTGRES_DB, config_name="alembic", revision=REVISION)
    user_id = uuid4()
    with engine.begin() as conn:
        _insert_user(conn, user_id)
    try:
        downgrade_postgres(
            database=POSTGRES_DB, config_name="alembic", revision=PREVIOUS_REVISION
        )
        assert _user_preference_values(engine, user_id) == DEFAULT_USER_VALUES
    finally:
        with engine.begin() as conn:
            conn.execute(text('DELETE FROM "user" WHERE id = :id'), {"id": user_id})
