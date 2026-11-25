"""add chat_artifact user_id

Revision ID: 4d900adc4242
Revises: c828aae2888b
Create Date: 2026-11-23 12:00:00.000000

Adds chat_artifact.user_id, the owner of the artifact's chat, and an index
of each user's artifacts by latest publish, which the artifacts_list tool
reads. The upgrade fills it from the chat. An artifact of a chat without an
owner can never be listed: the upgrade deletes it with the file records of
its versions and their thumbnails. Their stored objects stay in the file
store.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "4d900adc4242"
down_revision = "c828aae2888b"
branch_labels = None
depends_on = None

INDEX_NAME = "ix_chat_artifact_user_id_updated_at"
FK_NAME = "chat_artifact_user_id_fkey"
# Match the existing concurrent-index migrations; a retry repairs an invalid
# index.
LOCK_TIMEOUT = "60s"


def upgrade() -> None:
    bind = op.get_bind()
    schema: str = bind.execute(sa.text("SELECT current_schema()")).scalar_one()
    # The column marks a retry after the first phase committed.
    if "user_id" not in {
        column["name"]
        for column in sa.inspect(bind).get_columns("chat_artifact", schema=schema)
    }:
        op.add_column(
            "chat_artifact",
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        )
        op.execute(
            "UPDATE chat_artifact SET user_id = chat_session.user_id FROM "
            "chat_session WHERE chat_session.id = chat_artifact.chat_session_id"
        )
        # The version rows cascade from their file records; the artifacts go
        # next.
        op.execute(
            "DELETE FROM file_record WHERE file_id IN ("
            "SELECT version.file_id FROM chat_artifact_version version "
            "JOIN chat_artifact artifact ON artifact.id = version.artifact_id "
            "WHERE artifact.user_id IS NULL "
            "UNION SELECT version.thumbnail_file_id "
            "FROM chat_artifact_version version "
            "JOIN chat_artifact artifact ON artifact.id = version.artifact_id "
            "WHERE artifact.user_id IS NULL "
            "AND version.thumbnail_file_id IS NOT NULL)"
        )
        op.execute("DELETE FROM chat_artifact WHERE user_id IS NULL")
        op.alter_column("chat_artifact", "user_id", nullable=False)
        op.create_foreign_key(
            FK_NAME,
            "chat_artifact",
            "user",
            ["user_id"],
            ["id"],
            ondelete="CASCADE",
            postgresql_not_valid=True,
        )
    # Release the DDL locks before the concurrent index build and the
    # validation. env.py owns the transaction, so Alembic's autocommit_block
    # cannot be used.
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
                    f"ON {quoted_schema}.chat_artifact (user_id, updated_at DESC)"
                )
            conn.exec_driver_sql(
                f"ALTER TABLE {quoted_schema}.chat_artifact "
                f"VALIDATE CONSTRAINT {FK_NAME}"
            )
        finally:
            conn.exec_driver_sql("RESET lock_timeout")


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="chat_artifact")
    op.drop_constraint(FK_NAME, "chat_artifact", type_="foreignkey")
    op.drop_column("chat_artifact", "user_id")
