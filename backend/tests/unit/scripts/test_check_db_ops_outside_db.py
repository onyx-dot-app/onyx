"""The db-operations check flags statements and session calls outside the db
directories, leaves transaction control, passed sessions and look-alike
receivers alone, honors allow markers that give a reason, and ratchets the
count of each file against the baseline."""

from pathlib import Path

import pytest
from scripts import check_db_ops_outside_db

_IMPORTS = """\
import sqlalchemy as sa
from sqlalchemy import delete, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.engine.sql_engine import get_sqlalchemy_engine
from onyx.db.models import User
from onyx.db.users import fetch_user_by_id
"""
_FIRST_BODY_LINE = len(_IMPORTS.splitlines()) + 2


def _source(body: str, signature: str = "def f(db_session: Session) -> None:") -> str:
    indented = "\n".join(f"    {line}" for line in body.splitlines())
    return f"{_IMPORTS}{signature}\n{indented}\n"


def _found(body: str, signature: str = "def f(db_session: Session) -> None:") -> int:
    lines, _ = check_db_ops_outside_db.find_db_operations(_source(body, signature))
    return len(lines)


# Shapes taken from application files outside the db directories.
@pytest.mark.parametrize(
    "body",
    [
        # onyx/access/access.py
        "db_session.query(User).filter(User.id == user_id).scalar()",
        # onyx/llm/utils.py
        "db_session.scalar(stmt)",
        # onyx/redis/redis_connector_delete.py
        "db_session.scalars(stmt).all()",
        # onyx/background/celery/tasks/user_file_processing/tasks.py
        "uf = db_session.get(User, user_id)",
        "db_session.add(uf)",
        # onyx/background/celery/tasks/connector_deletion/tasks.py
        "db_session.delete(connector)",
        # onyx/background/task_utils.py
        "stmt = update(User).where(User.id == user_id).values(is_active=False)",
        "stmt = delete(User).where(User.id == user_id)",
        "stmt = sa.select(User)",
        # onyx/server/features/build/db/artifact.py
        "stmt = pg_insert(User).values(id=user_id).on_conflict_do_nothing()",
    ],
)
def test_statements_and_session_calls_are_flagged(body: str) -> None:
    assert _found(body) == 1


def test_execute_of_a_built_statement_is_one_line_per_call() -> None:
    assert _found("db_session.execute(\n    select(User.id)\n).scalars().all()") == 2


@pytest.mark.parametrize(
    ("signature", "body"),
    [
        # onyx/server/features/mcp/api.py
        ("def f(db: Session) -> None:", "db.execute(stmt)"),
        ("def f(db: Session | None = None) -> None:", "db.execute(stmt)"),
        # onyx/auth/users.py
        (
            "async def f(async_db_session: AsyncSession) -> None:",
            "user = await async_db_session.get(User, user_uuid)",
        ),
        # ee/onyx/server/tenants/schema_management.py
        (
            "def f(connection: Connection) -> None:",
            "connection.execute(stmt)",
        ),
        # onyx/background/celery/tasks/monitoring/tasks.py
        (
            "def f() -> None:",
            "with get_session_with_current_tenant() as session:\n"
            "    session.execute(stmt)",
        ),
        (
            "def f() -> None:",
            "with get_sqlalchemy_engine().connect() as conn:\n    pass\n"
            "engine = get_sqlalchemy_engine()\n"
            "with engine.connect() as conn:\n"
            "    conn.execute(stmt)",
        ),
        (
            "def f() -> None:",
            "with Session(engine) as fresh:\n    fresh.execute(stmt)",
        ),
        # A session kept on an object, as in onyx/key_value_store/store.py.
        (
            "def __init__(self, db: Session) -> None:",
            "self._db = db\nself._db.add(obj)",
        ),
        # The conventional name counts where a nested function has no annotation.
        ("def f(db_session) -> None:", "db_session.execute(stmt)"),
    ],
)
def test_sessions_are_found_by_type_factory_and_name(signature: str, body: str) -> None:
    assert _found(body, signature) == 1


@pytest.mark.parametrize(
    "body",
    [
        # The caller that owns the transaction controls it.
        "db_session.commit()",
        "db_session.flush()",
        "db_session.rollback()",
        "db_session.refresh(user)",
        "db_session.expire(user)",
        # A session passed to a db function.
        "user = fetch_user_by_id(db_session, user_id)",
        # onyx/auth/signup_rate_limit.py: a Redis pipeline.
        "pipe.execute()",
        # onyx/connectors/salesforce/sqlite_functions.py: a SQLite cursor.
        'cursor.execute("SELECT id FROM salesforce_objects")',
        # onyx/connectors/google_drive/source_operations.py: a Google API request.
        "service.files().get(fileId=file_id).execute()",
        # onyx/connectors/salesforce/salesforce_calls.py
        "sf_client.query(soql)",
        # HTTP sessions and plain containers share these method names.
        "session.get(url)",
        "seen_session_ids.add(ancestor)",
        "row.update({'name': name})",
        "settings.get('key')",
        # onyx/server/metrics/postgres_connection_pool.py: a dict of engines.
        "_registered: dict[str, Engine] = {}\n_registered.get(label)",
    ],
)
def test_other_calls_are_clean(body: str) -> None:
    assert _found(body) == 0


def test_builder_names_from_other_modules_are_clean() -> None:
    source = (
        "from select import select\n"
        "from onyx.utils.text import text\n"
        "ready = select([], [], [])\n"
        "label = text('x')\n"
    )
    assert check_db_ops_outside_db.find_db_operations(source) == ([], [])


@pytest.mark.parametrize(
    "body",
    [
        "db_session.execute(stmt)  # db-ops-outside-db: allow advisory lock, no query",
        "db_session.execute(  # db-ops-outside-db: allow: advisory lock\n    stmt\n)",
        "rows = db_session.execute(\n"
        "    select(User)  # db-ops-outside-db: allow built for a db function\n"
        ").all()  # db-ops-outside-db: allow advisory lock",
    ],
)
def test_allow_marker_with_a_reason_exempts_its_call(body: str) -> None:
    assert check_db_ops_outside_db.find_db_operations(_source(body)) == ([], [])


@pytest.mark.parametrize(
    "marker", ["# db-ops-outside-db: allow", "# db-ops-outside-db: allow  # noqa"]
)
def test_allow_marker_without_a_reason_is_reported(marker: str) -> None:
    lines, no_reason = check_db_ops_outside_db.find_db_operations(
        _source(f"db_session.execute(stmt)  {marker}")
    )
    assert lines == [_FIRST_BODY_LINE]
    assert no_reason == [_FIRST_BODY_LINE]


@pytest.mark.parametrize(
    ("path", "checked"),
    [
        ("backend/onyx/server/manage/users.py", True),
        ("backend/ee/onyx/server/tenants/provisioning.py", True),
        ("backend/onyx/db/users.py", False),
        ("backend/ee/onyx/db/user_group.py", False),
        ("backend/onyx/cache/postgres_backend.py", False),
        ("backend/alembic/versions/25053020dd5a_x.py", False),
        ("backend/tests/unit/onyx/test_x.py", False),
        ("backend/scripts/reset_postgres.py", False),
        ("backend/onyx/server/manage/users.txt", False),
    ],
)
def test_scope(path: str, checked: bool) -> None:
    assert check_db_ops_outside_db.is_checked(path) is checked


def test_ratchet_fails_on_a_rise_a_new_file_and_a_stale_baseline() -> None:
    baseline = {"a.py": 2, "b.py": 2, "c.py": 1, "gone.py": 3}
    operations = {"a.py": [4, 9, 12], "b.py": [7], "c.py": [3], "new.py": [5]}
    risen, stale = check_db_ops_outside_db.check(
        operations, baseline, existing=["a.py", "b.py", "c.py"]
    )
    assert risen == [
        "a.py: 3 (baseline 2), lines 4, 9, 12",
        "new.py: 1 (baseline 0), lines 5",
    ]
    assert stale == [
        "b.py: 1 (baseline 2)",
        "gone.py: file is gone (baseline 3)",
    ]


def test_baseline_round_trips_and_drops_clean_files(tmp_path: Path) -> None:
    path = tmp_path / "baseline.txt"
    path.write_text(check_db_ops_outside_db.format_baseline({"b.py": 2, "a.py": 0}))
    assert check_db_ops_outside_db.read_baseline(path) == {"b.py": 2}


def test_current_tree_matches_the_committed_baseline() -> None:
    assert check_db_ops_outside_db.main([]) == 0
