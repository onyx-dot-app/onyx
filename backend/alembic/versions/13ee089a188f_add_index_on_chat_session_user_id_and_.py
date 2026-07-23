"""add index on chat_session user_id and time_updated

Revision ID: 13ee089a188f
Revises: fe958f19e42b
Create Date: 2026-07-23 22:54:43.874508

Adds a composite btree index on (user_id, time_updated DESC) to back the
chat-history sidebar query (get_chat_sessions_by_user), which filters by
user_id and orders by time_updated DESC. Without it Postgres plans a Seq Scan
+ Sort that degrades linearly as chat_session grows.

chat_session is hot and frequently written (time_updated is bumped on every
message), so the index is built CONCURRENTLY to avoid blocking writes. This
project's alembic env.py sets search_path before configuring the migration
context, so the migration runs inside an externally-managed transaction and
op.get_context().autocommit_block() is unavailable. We instead commit the
pending migration transaction and build the index on a dedicated AUTOCOMMIT
connection (CREATE INDEX CONCURRENTLY cannot run inside a transaction block).
"""

from alembic import op
import sqlalchemy as sa
import logging

logger = logging.getLogger("alembic.runtime.migration")

# revision identifiers, used by Alembic.
revision = "13ee089a188f"
down_revision = "fe958f19e42b"
branch_labels = None
depends_on = None

INDEX_NAME = "ix_chat_session_user_id_time_updated"


def _existing_indexes(bind: sa.engine.Connection) -> list[str | None]:
    try:
        return [ix.get("name") for ix in sa.inspect(bind).get_indexes("chat_session")]
    except Exception:
        return []


def upgrade() -> None:
    bind = op.get_bind()
    if INDEX_NAME in _existing_indexes(bind):
        return

    logger.info("Creating index %s on chat_session (CONCURRENTLY)...", INDEX_NAME)
    # End alembic's transaction so CONCURRENTLY can run; otherwise the build
    # would wait forever on this still-open transaction's snapshot.
    bind.commit()
    with bind.engine.connect().execution_options(
        isolation_level="AUTOCOMMIT"
    ) as autocommit_conn:
        autocommit_conn.exec_driver_sql(
            f'CREATE INDEX CONCURRENTLY IF NOT EXISTS "{INDEX_NAME}" '
            "ON chat_session (user_id, time_updated DESC)"
        )
    logger.info("Created index %s", INDEX_NAME)


def downgrade() -> None:
    bind = op.get_bind()
    if INDEX_NAME not in _existing_indexes(bind):
        return

    logger.info("Dropping index %s on chat_session (CONCURRENTLY)...", INDEX_NAME)
    bind.commit()
    with bind.engine.connect().execution_options(
        isolation_level="AUTOCOMMIT"
    ) as autocommit_conn:
        autocommit_conn.exec_driver_sql(
            f'DROP INDEX CONCURRENTLY IF EXISTS "{INDEX_NAME}"'
        )
    logger.info("Dropped index %s", INDEX_NAME)
