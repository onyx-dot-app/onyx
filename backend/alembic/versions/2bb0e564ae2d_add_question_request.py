"""add question request

Create question_request for the questions that a chat response's agent asks
the user, with their answers.

Revision ID: 2bb0e564ae2d
Revises: ff11c4042c42
Create Date: 2026-11-17 10:55:07.301651

"""

import logging
import time
from collections.abc import Callable

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import DBAPIError

logger = logging.getLogger("alembic.runtime.migration")

# revision identifiers, used by Alembic.
revision = "2bb0e564ae2d"
down_revision = "ff11c4042c42"
branch_labels = None
depends_on = None

# Alembic runs all pending revisions of a schema in one transaction, so while
# this retries, the locks of earlier revisions stay held. Keep the budget short.
_LOCK_TIMEOUT = "5s"
_LOCK_ATTEMPTS = 6
_RETRY_DELAY_S = 2
# SQLSTATE lock_not_available: the error a lock_timeout raises.
_LOCK_NOT_AVAILABLE = "55P03"


def _with_bounded_lock_wait(change: Callable[[], None]) -> None:
    """Run a change with a bounded lock wait. The foreign keys to
    chat_session and chat_message wait for their open transactions, and chat
    writes queue behind that wait; each attempt runs in a savepoint, so a
    lock timeout retries instead of failing the migration."""
    bind = op.get_bind()
    for attempt in range(1, _LOCK_ATTEMPTS + 1):
        try:
            with bind.begin_nested():
                bind.execute(sa.text(f"SET LOCAL lock_timeout = '{_LOCK_TIMEOUT}'"))
                change()
            break
        except DBAPIError as e:
            # psycopg2 and SQLAlchemy's asyncpg adapter both set `pgcode` on
            # the driver error, but the DBAPI error type does not declare it.
            pgcode = getattr(e.orig, "pgcode", None)  # ods: ignore[getattr]
            if attempt == _LOCK_ATTEMPTS or pgcode != _LOCK_NOT_AVAILABLE:
                raise
            logger.warning(
                "A question_request change timed out waiting for a lock "
                "(attempt %s/%s). Retrying in %ss.",
                attempt,
                _LOCK_ATTEMPTS,
                _RETRY_DELAY_S,
            )
            time.sleep(_RETRY_DELAY_S)
    bind.execute(sa.text("SET LOCAL lock_timeout = DEFAULT"))


def _create_question_request() -> None:
    op.create_table(
        "question_request",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chat_session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chat_message_id", sa.Integer(), nullable=False),
        sa.Column("tool_call_id", sa.String(), nullable=False),
        sa.Column("questions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("answers", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column(
            "outcome",
            sa.Enum("ANSWERED", "CANCELLED", name="questionoutcome", native_enum=False),
            nullable=True,
        ),
        sa.Column(
            "answered_via",
            sa.Enum("CARD", "MESSAGE", name="questionansweredvia", native_enum=False),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["chat_session_id"], ["chat_session.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["chat_message_id"], ["chat_message.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_question_request_chat_message", "question_request", ["chat_message_id"]
    )
    op.create_index(
        "ix_question_request_chat_session", "question_request", ["chat_session_id"]
    )


def upgrade() -> None:
    _with_bounded_lock_wait(_create_question_request)


def downgrade() -> None:
    _with_bounded_lock_wait(lambda: op.drop_table("question_request"))
