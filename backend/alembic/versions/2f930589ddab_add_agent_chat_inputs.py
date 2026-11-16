"""Store agent messages and child results in the chat inbox.

Revision ID: 2f930589ddab
Revises: 7d675569f0bc
Create Date: 2026-11-11 18:03:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "2f930589ddab"
down_revision = "7d675569f0bc"
branch_labels = None
depends_on = None

# Match the existing concurrent-index migrations; a retry repairs invalid indexes.
LOCK_TIMEOUT = "60s"
# Branch walks and child-history queries join on these parent links.
PARENT_INDEXES = (
    ("ix_chat_message_parent_message_id", "chat_message", "parent_message_id"),
    ("ix_tool_call_parent_chat_message_id", "tool_call", "parent_chat_message_id"),
)
AGENT_REFERENCES = (
    ("invoking_tool_call_id", "tool_call"),
    ("source_response_id", "chat_message"),
    ("root_response_id", "chat_message"),
)
HUMAN_CHECK = (
    "(source = 'human' AND delivery IN ('send', 'queue', 'interrupt')) IS TRUE"
)
# IS TRUE: a NULL comparison makes CHECK pass, so require a true result.
SOURCE_CHECK = (
    "((source = 'human' AND delivery IN ('send', 'queue', 'interrupt') "
    "AND invoking_tool_call_id IS NULL AND max_steps IS NULL "
    "AND root_response_id IS NULL) OR "
    "(source = 'agent' AND delivery IN ('send', 'queue') "
    "AND invoking_tool_call_id IS NOT NULL AND max_steps > 0 "
    "AND root_response_id IS NOT NULL) OR "
    "(source = 'agent_result' AND delivery IS NULL "
    "AND source_response_id IS NOT NULL AND root_response_id IS NOT NULL)) "
    "IS TRUE"
)


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
    # The column phase commits together; its first column identifies a retry.
    columns = {
        column["name"]
        for column in sa.inspect(bind).get_columns("chat_input", schema=schema)
    }
    if "invoking_tool_call_id" not in columns:
        _add_agent_columns()
    # Release DDL locks and our snapshot before concurrent index construction.
    # env.py owns the transaction, so Alembic's autocommit_block cannot be used.
    bind.commit()
    with bind.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.exec_driver_sql(f"SET lock_timeout = '{LOCK_TIMEOUT}'")
        # A plain SET outlives the transaction on this connection. Reset it so a
        # pooled connection does not carry the timeout to its next user.
        try:
            quoted_schema = conn.dialect.identifier_preparer.quote_identifier(schema)
            for name, table, column in PARENT_INDEXES:
                qualified_name = f'{quoted_schema}."{name}"'
                state = _index_state(conn, qualified_name)
                if state is True:
                    continue
                if state is False:
                    conn.exec_driver_sql(f"DROP INDEX CONCURRENTLY {qualified_name}")
                conn.exec_driver_sql(
                    f'CREATE INDEX CONCURRENTLY "{name}" '
                    f"ON {quoted_schema}.{table} ({column})"
                )
        finally:
            conn.exec_driver_sql("RESET lock_timeout")


def _add_agent_columns() -> None:
    for column, table in AGENT_REFERENCES:
        op.add_column(
            "chat_input",
            sa.Column(
                column,
                sa.Integer(),
                sa.ForeignKey(f"{table}.id", ondelete="CASCADE"),
                nullable=True,
            ),
        )
        op.create_index(f"ix_chat_input_{column}", "chat_input", [column])
    op.add_column("chat_input", sa.Column("max_steps", sa.Integer(), nullable=True))
    op.add_column("chat_input", sa.Column("total_timeout_s", sa.Float(), nullable=True))
    op.drop_constraint("ck_chat_input_source", "chat_input", type_="check")
    op.create_check_constraint("ck_chat_input_source", "chat_input", SOURCE_CHECK)


def downgrade() -> None:
    for name, table, _ in PARENT_INDEXES:
        op.drop_index(name, table_name=table, if_exists=True)
    # The human-only schema cannot keep agent messages or child results.
    op.execute("DELETE FROM chat_input WHERE source <> 'human'")
    op.drop_constraint("ck_chat_input_source", "chat_input", type_="check")
    for column, _ in AGENT_REFERENCES:
        op.drop_index(f"ix_chat_input_{column}", table_name="chat_input")
        op.drop_column("chat_input", column)
    op.drop_column("chat_input", "max_steps")
    op.drop_column("chat_input", "total_timeout_s")
    op.create_check_constraint("ck_chat_input_source", "chat_input", HUMAN_CHECK)
