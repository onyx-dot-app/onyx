"""Native memory concurrency tests use temporary schemas, never live user rows."""

import asyncio
import os
from collections.abc import Generator
from contextlib import contextmanager
from typing import cast
from uuid import UUID, uuid4

import pytest
from pydantic_ai import ModelRetry
from pydantic_ai_harness.memory import (
    MemoryConflictError,
    MemoryOperation,
    MemoryOperationConflictError,
)
from sqlalchemy import Table, create_engine, inspect, select, text, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from onyx.db import agent_memory
from onyx.db.agent_memory import UserMemoryStore
from onyx.db.models import Memory, MemoryFileMetadata, MemoryOperationReceipt, ToolCall
from shared_configs.contextvars import CURRENT_INCOGNITO_RECORD_MODE_CONTEXTVAR


@pytest.fixture(scope="module")
def database_engine() -> Generator[Engine, None, None]:
    engine = create_engine(os.environ["ONYX_MEMORY_TEST_DATABASE_URL"])
    yield engine
    engine.dispose()


@pytest.fixture
def schemas(
    monkeypatch: pytest.MonkeyPatch,
    database_engine: Engine,
) -> Generator[dict[str, Engine], None, None]:
    engine = database_engine
    names = [f"native_memory_{uuid4().hex}" for _ in range(2)]
    engines: dict[str, Engine] = {}
    try:
        for name in names:
            with engine.begin() as connection:
                connection.execute(text(f'CREATE SCHEMA "{name}"'))
                connection.execute(
                    text(
                        f'CREATE TABLE "{name}"."user" (id uuid PRIMARY KEY, enable_memory_tool boolean NOT NULL DEFAULT true)'
                    )
                )
                scoped = connection.execution_options(schema_translate_map={None: name})
                cast(Table, Memory.__table__).create(scoped)
                cast(Table, MemoryFileMetadata.__table__).create(scoped)
                cast(Table, MemoryOperationReceipt.__table__).create(scoped)
            engines[name] = engine.execution_options(schema_translate_map={None: name})

        @contextmanager
        def session(*, tenant_id: str) -> Generator[Session, None, None]:
            with Session(engines[tenant_id]) as db:
                yield db

        monkeypatch.setattr(agent_memory, "get_session_with_tenant", session)
        yield engines
    finally:
        for name in names:
            with engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA IF EXISTS "{name}" CASCADE'))


def _user(engine: Engine, user_id: UUID) -> None:
    schema = engine.get_execution_options()["schema_translate_map"][None]
    with engine.begin() as connection:
        connection.execute(
            text(f'INSERT INTO "{schema}"."user" (id) VALUES (:id)'), {"id": user_id}
        )


def _store(schema: str, user: UUID) -> UserMemoryStore:
    return UserMemoryStore(tenant_id=schema, user_id=user, writable=True)


@pytest.mark.asyncio
async def test_concurrent_cas_receipts_and_user_tenant_isolation(
    schemas: dict[str, Engine],
) -> None:
    tenant, other_tenant = schemas
    owner, other_owner = uuid4(), uuid4()
    for name, user in ((tenant, owner), (tenant, other_owner), (other_tenant, owner)):
        _user(schemas[name], user)
    store = _store(tenant, owner)
    path = f"{store.scope}/preferences.md"
    first = await store.write(path, "dark mode", expected_version=None)
    writes = await asyncio.gather(
        store.write(path, "light mode", expected_version=first.version),
        store.write(path, "large text", expected_version=first.version),
        return_exceptions=True,
    )
    assert sum(isinstance(item, MemoryConflictError) for item in writes) == 1
    other = _store(tenant, other_owner)
    assert await other.read(f"{other.scope}/preferences.md", max_chars=100) is None
    other = _store(other_tenant, owner)
    assert await other.read(f"{other.scope}/preferences.md", max_chars=100) is None
    with pytest.raises(ValueError):
        await other.read(path, max_chars=100)
    current = await store.read(path, max_chars=100)
    assert current is not None
    operation = MemoryOperation(id="write-once", fingerprint="same-input")
    result = await store.write(
        path, "new preference", expected_version=current.version, operation=operation
    )
    replay = await store.write(
        path, "new preference", expected_version=current.version, operation=operation
    )
    assert replay.replayed and replay.version == result.version
    with pytest.raises(MemoryOperationConflictError):
        await store.get_operation(
            MemoryOperation(id="write-once", fingerprint="different-input")
        )


@pytest.mark.asyncio
async def test_legacy_ui_rows_versions_delete_and_incognito(
    schemas: dict[str, Engine],
) -> None:
    tenant = next(iter(schemas))
    owner = uuid4()
    _user(schemas[tenant], owner)
    with Session(schemas[tenant]) as session:
        row = Memory(user_id=owner, memory_text="legacy preference")
        session.add(row)
        session.commit()
        row_id = row.id
    store = _store(tenant, owner)
    path = f"{store.scope}/memories/{row_id}.md"
    original = await store.read(path, max_chars=6)
    assert original and original.truncated and original.content == "legacy"
    index = await store.read(f"{store.scope}/MEMORY.md", max_chars=1000)
    assert index and "legacy preference" in index.content
    with Session(schemas[tenant]) as session:
        session.execute(
            update(Memory)
            .where(Memory.id == row_id)
            .values(memory_text="edited through UI")
        )
        session.commit()
    with pytest.raises(MemoryConflictError):
        await store.write(path, "stale edit", expected_version=original.version)
    current = await store.read(path, max_chars=1000)
    assert current
    await store.delete(path, expected_version=current.version)
    assert await store.read(path, max_chars=1000) is None
    for mode in ("full_history", "usage_only"):
        token = CURRENT_INCOGNITO_RECORD_MODE_CONTEXTVAR.set(mode)
        try:
            with pytest.raises(ModelRetry):
                await store.read(path, max_chars=1000)
            with pytest.raises(ModelRetry):
                await store.write(path, "must not persist", expected_version=None)
        finally:
            CURRENT_INCOGNITO_RECORD_MODE_CONTEXTVAR.reset(token)
    with pytest.raises(ValueError):
        await store.read(f"{store.scope}/../escape.md", max_chars=1000)


@pytest.mark.asyncio
async def test_native_memory_capability_owns_writes_and_preserves_ui_ids(
    schemas: dict[str, Engine],
) -> None:
    from pydantic_ai import Agent
    from pydantic_ai.messages import (
        ModelMessage,
        ModelRequest,
        ModelResponse,
        TextPart,
        ToolCallPart,
        UserPromptPart,
    )
    from pydantic_ai.models.function import AgentInfo, FunctionModel

    from onyx.chat.agent_memory import create_memory_capability
    from onyx.chat.chat_state import ChatStateContainer
    from onyx.server.query_and_chat.placement import Placement

    tenant = next(iter(schemas))
    owner = uuid4()
    _user(schemas[tenant], owner)
    state = ChatStateContainer()
    capability = create_memory_capability(
        user_id=owner,
        tenant_id=tenant,
        inject_memory=True,
        writable=True,
        tool_id=42,
        state_container=state,
        placement=lambda _call: Placement(turn_index=0),
    )
    assert capability is not None
    requests: list[list[ModelMessage]] = []

    def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del info
        requests.append(list(messages))
        if len(requests) == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "write_memory",
                        {"file": "preferences.md", "content": "Prefers dark mode"},
                        "save-preference",
                    )
                ]
            )
        return ModelResponse(parts=[TextPart("Saved your preference.")])

    result = await Agent[None, str](
        FunctionModel(model), capabilities=[capability]
    ).run("Remember that I prefer dark mode")
    assert result.output == "Saved your preference."
    calls = state.get_tool_calls()
    assert len(calls) == 1 and calls[0].tool_call_id == "save-preference"
    store = _store(tenant, owner)
    saved = await store.read(f"{store.scope}/preferences.md", max_chars=1000)
    assert saved and saved.content == "Prefers dark mode\n"
    assert any(
        "Prefers dark mode" in str(part.content)
        for message in requests[-1]
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, UserPromptPart)
    )
    with Session(schemas[tenant]) as session:
        row = session.scalar(select(Memory).where(Memory.user_id == owner))
        assert row and str(row.id) in calls[0].tool_call_response


def test_memory_migration_upgrade_and_downgrade(schemas: dict[str, Engine]) -> None:
    import runpy
    from collections.abc import Callable
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    tenant = next(iter(schemas))
    migration = runpy.run_path(
        str(
            Path(__file__).parents[3]
            / "alembic/versions/86eac5e7c86e_add_native_agent_memory_file_metadata_.py"
        )
    )
    with schemas[tenant].begin() as connection:
        connection.execute(text(f'SET LOCAL search_path TO "{tenant}"'))
        connection.execute(
            text("DROP TABLE memory_operation_receipt, memory_file_metadata")
        )
        connection.execute(
            text(
                "CREATE TABLE security_settings (id integer PRIMARY KEY, llm_custom_config_env_injection boolean)"
            )
        )
        connection.execute(text("CREATE TABLE tool_call (id integer PRIMARY KEY)"))
        connection.execute(text("INSERT INTO tool_call (id) VALUES (42)"))
        with Operations.context(MigrationContext.configure(connection)):
            cast(Callable[[], None], migration["upgrade"])()
            assert (
                connection.execute(
                    text(
                        "SELECT count(*) FROM information_schema.tables WHERE table_schema=:schema AND table_name IN ('memory_operation_receipt','memory_file_metadata')"
                    ),
                    {"schema": tenant},
                ).scalar()
                == 2
            )
            inspector = inspect(connection)
            for model in (MemoryFileMetadata, MemoryOperationReceipt):
                table = cast(Table, model.__table__)
                migrated = {
                    column["name"]: (
                        column["nullable"],
                        column["type"].compile(dialect=connection.dialect),
                    )
                    for column in inspector.get_columns(table.name, schema=tenant)
                }
                expected = {
                    column.name: (
                        column.nullable,
                        column.type.compile(dialect=connection.dialect),
                    )
                    for column in table.columns
                }
                assert migrated == expected
                assert all(
                    key["options"].get("ondelete") == "CASCADE"
                    for key in inspector.get_foreign_keys(table.name, schema=tenant)
                )
            native_name = next(
                column
                for column in inspector.get_columns("tool_call", schema=tenant)
                if column["name"] == "tool_name"
            )
            declared = cast(Table, ToolCall.__table__).c.tool_name
            assert native_name["nullable"] == declared.nullable
            assert native_name["type"].compile(
                dialect=connection.dialect
            ) == declared.type.compile(dialect=connection.dialect)
            assert (
                connection.execute(
                    text("SELECT tool_name FROM tool_call WHERE id=42")
                ).scalar()
                is None
            )
            connection.execute(
                text("UPDATE tool_call SET tool_name='write_memory' WHERE id=42")
            )
            assert (
                connection.execute(
                    text("SELECT tool_name FROM tool_call WHERE id=42")
                ).scalar()
                == "write_memory"
            )
            cast(Callable[[], None], migration["downgrade"])()
            assert "tool_name" not in {
                column["name"]
                for column in inspect(connection).get_columns(
                    "tool_call", schema=tenant
                )
            }
            assert connection.execute(text("SELECT id FROM tool_call")).scalar() == 42
            assert not inspect(connection).has_table(
                "memory_file_metadata", schema=tenant
            )
            assert not inspect(connection).has_table(
                "memory_operation_receipt", schema=tenant
            )

            assert (
                connection.execute(
                    text(
                        "SELECT count(*) FROM information_schema.columns WHERE table_schema=:schema AND table_name='security_settings' AND column_name='llm_custom_config_env_injection'"
                    ),
                    {"schema": tenant},
                ).scalar()
                == 1
            )


@pytest.mark.asyncio
async def test_cancelled_memory_write_rolls_back_before_commit(
    schemas: dict[str, Engine],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from threading import Event

    tenant = next(iter(schemas))
    owner = uuid4()
    _user(schemas[tenant], owner)
    store = _store(tenant, owner)
    entered, release = Event(), Event()
    original_rows = store._rows

    def blocked_rows(session: Session) -> list[tuple[Memory, str]]:
        entered.set()
        assert release.wait(5)
        return original_rows(session)

    monkeypatch.setattr(store, "_rows", blocked_rows)
    task = asyncio.create_task(
        store.write(
            f"{store.scope}/cancelled.md",
            "Must not persist",
            expected_version=None,
            operation=MemoryOperation(id="cancelled-write", fingerprint="cancelled"),
        )
    )
    assert await asyncio.to_thread(entered.wait, 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    release.set()

    def verify() -> None:
        with Session(schemas[tenant]) as session:
            # Wait for the cancelled worker to release its transaction's user lock.
            schema = schemas[tenant].get_execution_options()["schema_translate_map"][
                None
            ]
            session.execute(
                text(f'SELECT id FROM "{schema}"."user" WHERE id=:id FOR UPDATE'),
                {"id": owner},
            )
            assert session.scalar(select(Memory).where(Memory.user_id == owner)) is None
            assert (
                session.get(MemoryOperationReceipt, (owner, "cancelled-write")) is None
            )

    await asyncio.to_thread(verify)
