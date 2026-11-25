"""chat command action approvals

Revision ID: 00a73eb4dccf
Revises: c2caf6a8285c
Create Date: 2026-11-24 10:00:00.000000

An action_approval row can belong to a command that a chat runs in its VM:
session_id becomes nullable, and chat_session_id and command_id are added.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "00a73eb4dccf"
down_revision = "c2caf6a8285c"
branch_labels = None
depends_on = None

FK_NAME = "fk_action_approval_chat_session_id"
INDEX_NAME = "ix_action_approval_chat_command"
LOCK_TIMEOUT = "60s"


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
    if "chat_session_id" not in {
        column["name"]
        for column in sa.inspect(bind).get_columns("action_approval", schema=schema)
    }:
        op.alter_column(
            "action_approval",
            "session_id",
            existing_type=postgresql.UUID(as_uuid=True),
            nullable=True,
        )
        op.add_column(
            "action_approval",
            sa.Column("chat_session_id", postgresql.UUID(as_uuid=True), nullable=True),
        )
        op.add_column(
            "action_approval",
            sa.Column("command_id", postgresql.UUID(as_uuid=True), nullable=True),
        )
        op.create_foreign_key(
            FK_NAME,
            "action_approval",
            "chat_session",
            ["chat_session_id"],
            ["id"],
            ondelete="CASCADE",
            postgresql_not_valid=True,
        )
    # Release DDL locks before the concurrent index build and the validation.
    # env.py owns the transaction, so Alembic's autocommit_block cannot be used.
    bind.commit()
    with bind.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.exec_driver_sql(f"SET lock_timeout = '{LOCK_TIMEOUT}'")
        try:
            quoted_schema = conn.dialect.identifier_preparer.quote_identifier(schema)
            qualified_name = f'{quoted_schema}."{INDEX_NAME}"'
            state = _index_state(conn, qualified_name)
            if state is False:
                conn.exec_driver_sql(f"DROP INDEX CONCURRENTLY {qualified_name}")
            if state is not True:
                conn.exec_driver_sql(
                    f'CREATE INDEX CONCURRENTLY "{INDEX_NAME}" '
                    f"ON {quoted_schema}.action_approval (chat_session_id, command_id)"
                )
            conn.exec_driver_sql(
                f"ALTER TABLE {quoted_schema}.action_approval "
                f"VALIDATE CONSTRAINT {FK_NAME}"
            )
        finally:
            conn.exec_driver_sql("RESET lock_timeout")


def downgrade() -> None:
    op.execute("DELETE FROM action_approval WHERE session_id IS NULL")
    op.drop_index(INDEX_NAME, table_name="action_approval")
    op.drop_constraint(FK_NAME, "action_approval", type_="foreignkey")
    op.drop_column("action_approval", "command_id")
    op.drop_column("action_approval", "chat_session_id")
    op.alter_column(
        "action_approval",
        "session_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )
