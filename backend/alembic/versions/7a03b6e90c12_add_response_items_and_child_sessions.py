"""Store agent responses, child conversations, and resumable checkpoints.

Revision ID: 7a03b6e90c12
Revises: a27d64f7b810
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "7a03b6e90c12"
down_revision = "a27d64f7b810"
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
    # The schema phase commits together; its final table identifies a retry.
    if not sa.inspect(bind).has_table("chat_response_checkpoint", schema=schema):
        _add_response_storage()
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
            ("chat_message", "ck_chat_message_response_status"),
            ("tool_call", "ck_tool_call_operation_status"),
        ):
            conn.exec_driver_sql(
                f"ALTER TABLE {quoted_schema}.{table} VALIDATE CONSTRAINT {constraint}"
            )


def _add_response_storage() -> None:
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
    op.create_check_constraint(
        "ck_chat_message_response_status",
        "chat_message",
        "response_status IN ('running', 'suspended', 'complete', 'limit', 'cancelled', 'error')",
        postgresql_not_valid=True,
    )
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
        sa.Column("tool_name", sa.String(), nullable=True),
        sa.Column("operation_status", sa.String(), nullable=True),
        sa.Column("result", postgresql.JSONB(), nullable=True),
    ):
        op.add_column("tool_call", column)
    op.create_check_constraint(
        "ck_tool_call_operation_status",
        "tool_call",
        "operation_status IN ('running', 'complete', 'cancelled', 'error')",
        postgresql_not_valid=True,
    )
    op.create_table(
        "chat_response_message",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "chat_message_id",
            sa.Integer(),
            sa.ForeignKey("chat_message.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("step_index", sa.Integer(), nullable=False),
        sa.Column("generation_status", sa.String(), nullable=True),
        sa.Column("is_answer", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("message", postgresql.JSONB(), nullable=True),
        sa.Column(
            "tool_call_id",
            sa.Integer(),
            sa.ForeignKey("tool_call.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("rendering", postgresql.JSONB(), nullable=True),
        sa.UniqueConstraint(
            "chat_message_id", "position", name="uq_response_message_position"
        ),
        sa.UniqueConstraint("tool_call_id", name="uq_response_message_tool"),
        sa.CheckConstraint(
            "generation_status IN ('running', 'complete', 'cancelled', 'error')",
            name="ck_response_message_generation_status",
        ),
        sa.CheckConstraint(
            "position >= 0 AND step_index >= 0", name="ck_response_message_position"
        ),
        sa.CheckConstraint(
            "(message IS NOT NULL AND tool_call_id IS NULL AND generation_status IS NOT NULL) OR (message IS NULL AND tool_call_id IS NOT NULL AND generation_status IS NULL AND NOT is_answer)",
            name="ck_response_message_kind",
        ),
    )
    op.create_index(
        "uq_response_message_step",
        "chat_response_message",
        ["chat_message_id", "step_index"],
        unique=True,
        postgresql_where=sa.text("message IS NOT NULL"),
    )
    op.create_index(
        "uq_response_message_answer",
        "chat_response_message",
        ["chat_message_id"],
        unique=True,
        postgresql_where=sa.text("is_answer"),
    )

    op.add_column("chat_message", sa.Column("run_id", sa.String(), nullable=True))
    op.create_table(
        "chat_response_checkpoint",
        sa.Column(
            "chat_message_id",
            sa.Integer(),
            sa.ForeignKey("chat_message.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "ownership_version", sa.BigInteger(), server_default="0", nullable=False
        ),
        sa.Column("state", postgresql.JSONB(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("chat_response_checkpoint")
    op.drop_constraint("uq_chat_message_run_id", "chat_message", type_="unique")
    op.drop_column("chat_message", "run_id")

    # The public answer projections remain readable by the original schema.
    op.execute("""
        UPDATE tool_call SET tool_call_response = CASE jsonb_typeof(result->'content')
            WHEN 'string' THEN result->>'content'
            ELSE coalesce((SELECT string_agg(block->>'text', '' ORDER BY ordinal)
                FROM jsonb_array_elements(result->'content') WITH ORDINALITY AS blocks(block, ordinal)
                WHERE block->>'type' = 'text'), '') END
        WHERE result IS NOT NULL AND result <> 'null'::jsonb
    """)
    op.drop_table("chat_response_message")
    op.execute("DELETE FROM chat_session WHERE spawned_by_message_id IS NOT NULL")
    op.execute("DELETE FROM tool_call WHERE tool_id IS NULL")
    op.alter_column("tool_call", "tool_id", existing_type=sa.Integer(), nullable=False)
    op.drop_constraint("ck_chat_message_response_status", "chat_message", type_="check")
    op.drop_constraint("ck_tool_call_operation_status", "tool_call", type_="check")
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
        "tool_name",
        "operation_status",
        "result",
    ):
        op.drop_column("tool_call", column)
