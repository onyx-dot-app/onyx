"""Add execution metadata and child-session links.

Revision ID: 9d8f310ac672
Revises: 6b4e821c0a93
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "9d8f310ac672"
down_revision = "6b4e821c0a93"
branch_labels = None
depends_on = None


def _index_state(conn: sa.engine.Connection, qualified_name: str) -> bool | None:
    """An interrupted concurrent build can leave an invalid index."""
    return conn.execute(
        sa.text(
            "SELECT i.indisvalid FROM pg_index i "
            "WHERE i.indexrelid = to_regclass(:qualified_name)"
        ),
        {"qualified_name": qualified_name},
    ).scalar_one_or_none()


def upgrade() -> None:
    bind = op.get_bind()
    schema: str = bind.execute(sa.text("SELECT current_schema()")).scalar_one()
    # The metadata phase commits together; its final column identifies a retry.
    if "run_id" not in {
        column["name"]
        for column in sa.inspect(bind).get_columns("chat_message", schema=schema)
    }:
        _add_execution_metadata()
    # Release DDL locks and our snapshot before concurrent index construction.
    # env.py owns the transaction, so Alembic's autocommit_block cannot be used.
    bind.commit()
    with bind.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        quoted_schema = conn.dialect.identifier_preparer.quote_identifier(schema)
        for name, statement in (
            (
                "ix_chat_session_spawned_by_message_id",
                'CREATE INDEX CONCURRENTLY "ix_chat_session_spawned_by_message_id" '
                f"ON {quoted_schema}.chat_session (spawned_by_message_id)",
            ),
            (
                "ix_chat_message_invoking_tool_call_id",
                'CREATE INDEX CONCURRENTLY "ix_chat_message_invoking_tool_call_id" '
                f"ON {quoted_schema}.chat_message (invoking_tool_call_id)",
            ),
            (
                "uq_chat_message_run_id",
                'CREATE UNIQUE INDEX CONCURRENTLY "uq_chat_message_run_id" '
                f"ON {quoted_schema}.chat_message (run_id)",
            ),
        ):
            qualified_name = f'{quoted_schema}."{name}"'
            state = _index_state(conn, qualified_name)
            if state is True:
                continue
            if state is False:
                conn.exec_driver_sql(f"DROP INDEX CONCURRENTLY {qualified_name}")
            conn.exec_driver_sql(statement)

        if not any(
            constraint["name"] == "uq_chat_message_run_id"
            for constraint in sa.inspect(conn).get_unique_constraints(
                "chat_message", schema=schema
            )
        ):
            conn.exec_driver_sql(
                f"ALTER TABLE {quoted_schema}.chat_message ADD CONSTRAINT "
                "uq_chat_message_run_id UNIQUE USING INDEX uq_chat_message_run_id"
            )
        # Validate only after releasing the initial ALTER TABLE locks.
        for table, constraint in (
            ("chat_session", "fk_chat_session_spawned_by_message"),
            ("chat_message", "fk_chat_message_invocation"),
        ):
            conn.exec_driver_sql(
                f"ALTER TABLE {quoted_schema}.{table} VALIDATE CONSTRAINT {constraint}"
            )


def _add_execution_metadata() -> None:
    op.alter_column("tool_call", "tool_id", existing_type=sa.Integer(), nullable=True)
    op.add_column(
        "chat_session", sa.Column("spawned_by_message_id", sa.Integer(), nullable=True)
    )
    op.add_column("chat_session", sa.Column("agent_name", sa.String(), nullable=True))
    op.add_column(
        "chat_session",
        sa.Column("restoration_config", postgresql.JSONB(), nullable=True),
    )
    op.create_foreign_key(
        "fk_chat_session_spawned_by_message",
        "chat_session",
        "chat_message",
        ["spawned_by_message_id"],
        ["id"],
        ondelete="CASCADE",
        postgresql_not_valid=True,
    )
    for column in (
        sa.Column("response_status", sa.String(), nullable=True),
        sa.Column("response_failure", postgresql.JSONB(), nullable=True),
        sa.Column("invoking_tool_call_id", sa.Integer(), nullable=True),
    ):
        op.add_column("chat_message", column)
    op.create_foreign_key(
        "fk_chat_message_invocation",
        "chat_message",
        "tool_call",
        ["invoking_tool_call_id"],
        ["id"],
        ondelete="CASCADE",
        postgresql_not_valid=True,
    )
    for column in (
        sa.Column("operation_status", sa.String(), nullable=True),
        sa.Column("result", postgresql.JSONB(), nullable=True),
    ):
        op.add_column("tool_call", column)
    op.add_column("chat_message", sa.Column("run_id", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_constraint("uq_chat_message_run_id", "chat_message", type_="unique")
    op.drop_column("chat_message", "run_id")

    # The public answer projections remain readable by the original schema.
    op.execute("""
        UPDATE tool_call SET tool_call_response = result->>'content'
        WHERE result IS NOT NULL AND result <> 'null'::jsonb
    """)
    op.execute("DELETE FROM chat_session WHERE spawned_by_message_id IS NOT NULL")
    op.execute("DELETE FROM tool_call WHERE tool_id IS NULL")
    op.alter_column("tool_call", "tool_id", existing_type=sa.Integer(), nullable=False)
    for column in (
        "response_status",
        "response_failure",
        "invoking_tool_call_id",
    ):
        op.drop_column("chat_message", column)
    for column in (
        "spawned_by_message_id",
        "agent_name",
        "restoration_config",
    ):
        op.drop_column("chat_session", column)
    for column in (
        "operation_status",
        "result",
    ):
        op.drop_column("tool_call", column)
