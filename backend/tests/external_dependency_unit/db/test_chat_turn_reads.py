"""Turn preparation reads each row once."""

from sqlalchemy import text
from sqlalchemy.orm import Session

from onyx.db.chat import (
    CHAT_RESPONSE_LOCK_TIMEOUT_MS,
    CHAT_RESPONSE_STATEMENT_TIMEOUT_MS,
    configure_response_transaction__no_commit,
)


def test_response_transaction_sets_both_timeouts_in_one_statement(
    db_session: Session, executed_sql: list[str]
) -> None:
    try:
        executed_sql.clear()
        configure_response_transaction__no_commit(db_session)

        assert len(executed_sql) == 1
        for setting, expected_ms in (
            ("statement_timeout", CHAT_RESPONSE_STATEMENT_TIMEOUT_MS),
            ("lock_timeout", CHAT_RESPONSE_LOCK_TIMEOUT_MS),
        ):
            assert db_session.scalar(
                text(
                    "SELECT current_setting(:setting)::interval"
                    " = make_interval(secs => :ms / 1000.0)"
                ),
                {"setting": setting, "ms": expected_ms},
            )
    finally:
        db_session.rollback()
