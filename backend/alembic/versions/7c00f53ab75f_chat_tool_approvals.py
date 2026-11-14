"""chat tool approvals

Create approval_request for chat tool calls that wait for the user. Chat ran
MCP tools without approval, so existing MCP tools keep running without
approval in chat (an Auto-approve workspace policy) when their server is not
available in Craft, or when the tenant has never used Craft (no build
sessions): the flag that made servers available in Craft was set on every
server that existed when it was added, and a deployment without Craft does not
show it. Tools of Craft servers in a tenant that uses Craft keep their Craft
policies. Existing workspace policies are kept.

Revision ID: 7c00f53ab75f
Revises: 414dfccc5e24
Create Date: 2026-11-12 22:26:46.202126

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
revision = "7c00f53ab75f"
down_revision = "414dfccc5e24"
branch_labels = None
depends_on = None

# Alembic runs all pending revisions of a schema in one transaction, so while
# this retries, the locks of earlier revisions stay held. Keep the budget short.
_LOCK_TIMEOUT = "5s"
_LOCK_ATTEMPTS = 6
_RETRY_DELAY_S = 2
# SQLSTATE lock_not_available: the error a lock_timeout raises.
_LOCK_NOT_AVAILABLE = "55P03"


def _is_lock_timeout(error: DBAPIError) -> bool:
    # psycopg2 and SQLAlchemy's asyncpg adapter both set `pgcode` on the
    # driver error, but the DBAPI error type does not declare it.
    pgcode = getattr(error.orig, "pgcode", None)  # ods: ignore[getattr]
    return pgcode == _LOCK_NOT_AVAILABLE


def _with_bounded_lock_wait(change: Callable[[], None]) -> None:
    """Runs a change of this migration with a bounded lock wait.

    Creating or dropping foreign keys to chat_session, chat_message and
    gated_app waits for their open transactions, and the transaction then
    holds those locks until it ends. Chat writes queue behind any wait. A short
    lock_timeout keeps each wait short; each attempt runs in a savepoint, so a
    timeout retries instead of failing the migration.
    """
    bind = op.get_bind()
    for attempt in range(1, _LOCK_ATTEMPTS + 1):
        try:
            with bind.begin_nested():
                bind.execute(sa.text(f"SET LOCAL lock_timeout = '{_LOCK_TIMEOUT}'"))
                change()
            break
        except DBAPIError as e:
            # Only a lock timeout is worth a retry. Raise other errors at once.
            if attempt == _LOCK_ATTEMPTS or not _is_lock_timeout(e):
                raise
            logger.warning(
                "A chat tool approvals change timed out waiting for a lock "
                "(attempt %s/%s). Retrying in %ss.",
                attempt,
                _LOCK_ATTEMPTS,
                _RETRY_DELAY_S,
            )
            time.sleep(_RETRY_DELAY_S)
    bind.execute(sa.text("SET LOCAL lock_timeout = DEFAULT"))


def _create_approval_request() -> None:
    op.create_table(
        "approval_request",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chat_session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chat_message_id", sa.Integer(), nullable=False),
        sa.Column("gated_app_id", sa.Integer(), nullable=False),
        sa.Column("action_id", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "decision",
            sa.Enum(
                "APPROVED",
                "REJECTED",
                "EXPIRED",
                name="approvaldecision",
                native_enum=False,
            ),
            nullable=True,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "decided_via",
            sa.Enum(
                "USER",
                "PRE_APPROVAL",
                "SESSION_GRANT",
                "POLICY",
                name="approvaldecidedvia",
                native_enum=False,
            ),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["chat_session_id"], ["chat_session.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["chat_message_id"], ["chat_message.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["gated_app_id"], ["gated_app.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_approval_request_session_action",
        "approval_request",
        ["chat_session_id", "gated_app_id", "action_id"],
    )
    op.create_index(
        "ix_approval_request_chat_message", "approval_request", ["chat_message_id"]
    )


def _drop_approval_request() -> None:
    op.drop_index("ix_approval_request_chat_message", table_name="approval_request")
    op.drop_index("ix_approval_request_session_action", table_name="approval_request")
    op.drop_table("approval_request")


def _keep_chat_auto_approve() -> None:
    """Chat ran MCP tools without approval. Keep that for tools that exist
    now, except on servers that a tenant that uses Craft makes available in
    Craft. A server or policy that the application writes meanwhile wins."""
    keeps_auto_approve = (
        "(NOT server.available_in_craft OR NOT EXISTS (SELECT 1 FROM build_session))"
    )
    op.execute(  # migration-determinism: allow (copies existing rows, not seeded data)
        f"""
        INSERT INTO gated_app (mcp_server_id)
        SELECT server.id FROM mcp_server AS server
        WHERE {keeps_auto_approve}
        ON CONFLICT (mcp_server_id) DO NOTHING
        """
    )
    op.execute(  # migration-determinism: allow (copies existing rows, not seeded data)
        f"""
        INSERT INTO workspace_action_policy (gated_app_id, action_id, policy)
        SELECT DISTINCT gated_app.id, tool.name, 'ALWAYS'
        FROM tool
        JOIN mcp_server AS server ON server.id = tool.mcp_server_id
        JOIN gated_app ON gated_app.mcp_server_id = server.id
        WHERE {keeps_auto_approve}
        ON CONFLICT (gated_app_id, action_id) DO NOTHING
        """
    )


def upgrade() -> None:
    _with_bounded_lock_wait(_create_approval_request)
    # The chat tables stay locked until the transaction ends, and an insert
    # can wait on a concurrent write of the same server or policy.
    _with_bounded_lock_wait(_keep_chat_auto_approve)


def downgrade() -> None:
    # The Auto-approve policies stay; they are valid without this table.
    _with_bounded_lock_wait(_drop_approval_request)
