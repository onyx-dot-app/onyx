"""Queries written for a partial index must be able to use it. Postgres uses a
partial index only when it can prove the query's filter implies the index
predicate, and it does not match ``col IS true`` to ``WHERE col``. Each test
EXPLAINs the SQL the function sends, with sequential scans off, so the plan
shows whether the partial index is a candidate."""

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import event, text
from sqlalchemy.orm import Session

from onyx.db.credentials import delete_stale_draft_credentials
from onyx.db.incognito import stale_unadopted_upload_ids


def _explain_first_query(
    db_session: Session, sql_prefix: str, run: Callable[[], object]
) -> str:
    captured: list[tuple[str, Any]] = []

    def _capture(*args: Any) -> None:
        _, _, statement, parameters, _, _ = args
        if statement.lstrip().upper().startswith(sql_prefix):
            captured.append((statement, parameters))

    engine = db_session.get_bind()
    event.listen(engine, "before_cursor_execute", _capture)
    try:
        run()
    finally:
        event.remove(engine, "before_cursor_execute", _capture)
    db_session.rollback()
    statement, parameters = captured[0]

    db_session.execute(text("SET LOCAL enable_seqscan = off"))
    plan = "\n".join(
        db_session.connection()
        .exec_driver_sql(f"EXPLAIN {statement}", parameters)
        .scalars()
    )
    db_session.rollback()
    return plan


def test_incognito_sweep_uses_its_partial_index(db_session: Session) -> None:
    plan = _explain_first_query(
        db_session, "SELECT", lambda: stale_unadopted_upload_ids(db_session)
    )
    assert "ix_user_file_incognito_sweep" in plan, plan


def test_stale_draft_cleanup_uses_its_partial_index(db_session: Session) -> None:
    # Nothing is this old, so the cleanup deletes no rows.
    long_ago = datetime(2000, 1, 1, tzinfo=timezone.utc)
    plan = _explain_first_query(
        db_session,
        "SELECT",
        lambda: delete_stale_draft_credentials(db_session, updated_before=long_ago),
    )
    assert "ix_credential_draft_time_updated" in plan, plan
