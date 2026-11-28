"""add chat_artifact index_status

Revision ID: c14c2689b392
Revises: 78852b5a0db6
Create Date: 2026-11-24 12:00:00.000000

Adds the search indexing state of each published file: chat_artifact
index_status (PENDING, INDEXED, FAILED or REMOVED) and index_attempts, and a
partial index of the PENDING rows, which the indexing beat reads. The files of
live chats start PENDING, so the beat also indexes the files published before
this revision; the files of deleted chats start REMOVED.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c14c2689b392"
down_revision = "78852b5a0db6"
branch_labels = None
depends_on = None

INDEX_NAME = "ix_chat_artifact_index_pending"
# Match the existing concurrent-index migrations; a retry repairs an invalid
# index.
LOCK_TIMEOUT = "60s"


def upgrade() -> None:
    bind = op.get_bind()
    schema: str = bind.execute(sa.text("SELECT current_schema()")).scalar_one()
    # The column marks a retry after the first phase committed.
    if "index_status" not in {
        column["name"]
        for column in sa.inspect(bind).get_columns("chat_artifact", schema=schema)
    }:
        # Constant defaults: both additions change only the catalog.
        op.add_column(
            "chat_artifact",
            sa.Column(
                "index_status",
                sa.Enum(
                    "PENDING",
                    "INDEXED",
                    "FAILED",
                    "REMOVED",
                    name="chatartifactindexstatus",
                    native_enum=False,
                ),
                nullable=False,
                server_default="PENDING",
            ),
        )
        op.add_column(
            "chat_artifact",
            sa.Column(
                "index_attempts",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
        )
    # Release the ADD COLUMN lock before the update reads and writes rows.
    bind.commit()
    # The files of deleted chats have no document to write. A retry gives the
    # same result.
    op.execute(
        "UPDATE chat_artifact SET index_status = 'REMOVED' "
        "FROM chat_session "
        "WHERE chat_session.id = chat_artifact.chat_session_id "
        "AND chat_session.deleted AND chat_artifact.index_status = 'PENDING'"
    )
    # Release the DDL locks before the concurrent index build. env.py owns the
    # transaction, so Alembic's autocommit_block cannot be used.
    bind.commit()
    with bind.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.exec_driver_sql(f"SET lock_timeout = '{LOCK_TIMEOUT}'")
        # A plain SET outlives the transaction on this connection; reset it so
        # a pooled connection does not keep it.
        try:
            quoted_schema = conn.dialect.identifier_preparer.quote_identifier(schema)
            qualified_name = f'{quoted_schema}."{INDEX_NAME}"'
            # An interrupted concurrent build can leave an invalid index.
            valid = conn.execute(
                sa.text(
                    "SELECT i.indisvalid FROM pg_index i "
                    "WHERE i.indexrelid = to_regclass(:qualified_name)"
                ),
                {"qualified_name": qualified_name},
            ).scalar_one_or_none()
            if valid is False:
                conn.exec_driver_sql(f"DROP INDEX CONCURRENTLY {qualified_name}")
            if valid is not True:
                conn.exec_driver_sql(
                    f'CREATE INDEX CONCURRENTLY "{INDEX_NAME}" '
                    f"ON {quoted_schema}.chat_artifact (id) "
                    "WHERE index_status = 'PENDING'"
                )
        finally:
            conn.exec_driver_sql("RESET lock_timeout")


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="chat_artifact")
    op.drop_column("chat_artifact", "index_attempts")
    op.drop_column("chat_artifact", "index_status")
