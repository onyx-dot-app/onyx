"""add preview_file_id to chat files

Revision ID: a4253e609025
Revises: ce6d912380d7
Create Date: 2026-11-25 14:08:25.022232

Adds `preview_file_id` to chat_artifact_version and user_file: the file record
of the PDF that the sandbox VM makes of a PowerPoint or Word file, for its
preview. Each column links one file record, unique, and a delete of that
record clears the link.

Also indexes user_file.file_id, not unique: several user files can share one
file, and the preview finds the file's user file by it.

user_file can be large, so the foreign keys are added NOT VALID, and after a
commit the indexes build concurrently, the unique ones become the unique
constraints, and the foreign keys are validated. A retry repairs an index
that an interrupted build left invalid.

A downgrade drops the columns and the file_id index. The preview PDFs stay in the file store with
no link, and no delete removes them.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "a4253e609025"
down_revision = "ce6d912380d7"
branch_labels = None
depends_on = None

# Match the existing concurrent-index migrations.
LOCK_TIMEOUT = "60s"
TABLES = ("chat_artifact_version", "user_file")
FILE_ID_INDEX = "ix_user_file_file_id"


def upgrade() -> None:
    bind = op.get_bind()
    schema: str = bind.execute(sa.text("SELECT current_schema()")).scalar_one()
    for table in TABLES:
        if "preview_file_id" in {
            column["name"] for column in sa.inspect(bind).get_columns(table, schema)
        }:
            continue
        op.add_column(table, sa.Column("preview_file_id", sa.String(), nullable=True))
        op.create_foreign_key(
            f"{table}_preview_file_id_fkey",
            table,
            "file_record",
            ["preview_file_id"],
            ["file_id"],
            ondelete="SET NULL",
            postgresql_not_valid=True,
        )
    # Release the DDL locks before the concurrent index builds. env.py owns
    # the transaction, so Alembic's autocommit_block cannot be used.
    bind.commit()
    with bind.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.exec_driver_sql(f"SET lock_timeout = '{LOCK_TIMEOUT}'")
        # A plain SET outlives the transaction on this connection. Reset it so
        # a pooled connection does not carry the timeout to its next user.
        try:
            quoted_schema = conn.dialect.identifier_preparer.quote_identifier(schema)
            for table in TABLES:
                _add_unique_constraint_and_validate(conn, quoted_schema, table)
            _build_index(conn, quoted_schema, FILE_ID_INDEX, "user_file (file_id)")
        finally:
            conn.exec_driver_sql("RESET lock_timeout")


def _add_unique_constraint_and_validate(
    conn: sa.engine.Connection, quoted_schema: str, table: str
) -> None:
    constraint = f"{table}_preview_file_id_key"
    exists = conn.execute(
        sa.text(
            "SELECT 1 FROM pg_constraint "
            "WHERE conname = :name AND connamespace = to_regnamespace(:schema)"
        ),
        {"name": constraint, "schema": quoted_schema},
    ).scalar_one_or_none()
    if exists is None:
        _build_index(
            conn, quoted_schema, constraint, f"{table} (preview_file_id)", unique=True
        )
        conn.exec_driver_sql(
            f"ALTER TABLE {quoted_schema}.{table} "
            f"ADD CONSTRAINT {constraint} UNIQUE USING INDEX {constraint}"
        )
    conn.exec_driver_sql(
        f"ALTER TABLE {quoted_schema}.{table} "
        f"VALIDATE CONSTRAINT {table}_preview_file_id_fkey"
    )


def _build_index(
    conn: sa.engine.Connection,
    quoted_schema: str,
    name: str,
    target: str,
    *,
    unique: bool = False,
) -> None:
    """Build the index `name` on `target` ("table (column)") concurrently,
    unless a valid one exists. An invalid one, which an interrupted build
    leaves, is dropped and built again."""
    index = f"{quoted_schema}.{name}"
    valid = conn.execute(
        sa.text(
            "SELECT i.indisvalid FROM pg_index i "
            "WHERE i.indexrelid = to_regclass(:index)"
        ),
        {"index": index},
    ).scalar_one_or_none()
    if valid is False:
        conn.exec_driver_sql(f"DROP INDEX CONCURRENTLY {index}")
    if valid is not True:
        conn.exec_driver_sql(
            f"CREATE {'UNIQUE ' if unique else ''}INDEX CONCURRENTLY {name} "
            f"ON {quoted_schema}.{target}"
        )


def downgrade() -> None:
    op.drop_index(FILE_ID_INDEX, table_name="user_file", if_exists=True)
    for table in TABLES:
        op.drop_column(table, "preview_file_id")
