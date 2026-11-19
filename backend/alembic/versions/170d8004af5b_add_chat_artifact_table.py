"""add chat_artifact table

Revision ID: 170d8004af5b
Revises: e08a3dc8052a
Create Date: 2026-11-19 15:30:00.000000

A chat_artifact row links a published file (FileOrigin.CHAT_ARTIFACT) to its
root chat, with the file's VM path and title. The backfill reads the chat from
the file ID (`chat-artifact-<chat ID>-<hex>`) and the path and title from the
file record's metadata, which a file can lack. It skips files whose chat no
longer exists. The foreign keys come after the backfill, so the scan of
file_record does not hold locks on file_record and chat_session.

A downgrade drops the table. A published file whose ID has no chat prefix then
leaves its chat's output panel. Users also lose access to it when its response
was not saved.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "170d8004af5b"
down_revision = "e08a3dc8052a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_artifact",
        sa.Column("file_id", sa.String(), nullable=False),
        sa.Column("chat_session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("path", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("file_id"),
    )
    op.create_index(
        "ix_chat_artifact_chat_session_id", "chat_artifact", ["chat_session_id"]
    )
    op.execute(
        """
        INSERT INTO chat_artifact (file_id, chat_session_id, path, title, created_at)
        SELECT
            f.file_id,
            s.id,
            f.file_metadata ->> 'published_path',
            f.file_metadata ->> 'published_title',
            f.created_at
        FROM file_record f
        JOIN chat_session s
            -- The CASE keeps the cast from running on another ID
            ON s.id = CASE
                WHEN f.file_id ~ '^chat-artifact-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}-'
                THEN CAST(substring(f.file_id FROM 15 FOR 36) AS uuid)
            END
        WHERE f.file_origin = 'CHAT_ARTIFACT'
        """
    )
    op.create_foreign_key(
        "chat_artifact_file_id_fkey",
        "chat_artifact",
        "file_record",
        ["file_id"],
        ["file_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "chat_artifact_chat_session_id_fkey",
        "chat_artifact",
        "chat_session",
        ["chat_session_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_table("chat_artifact")
