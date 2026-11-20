"""add chat_artifact tables

Revision ID: 170d8004af5b
Revises: e08a3dc8052a
Create Date: 2026-11-19 15:30:00.000000

Creates chat_artifact and chat_artifact_version: the files that the model
published in a chat, as versions of one artifact per path.

A downgrade drops the tables. Published files then leave their chat's file
list and lose their versions. Their IDs carry no chat, so they also lose
access unless a saved message lists them, and a hard chat delete leaves them
in the file store. An upgrade after the downgrade does not restore them.
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
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chat_session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["chat_session_id"], ["chat_session.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("chat_session_id", "path"),
    )
    op.create_table(
        "chat_artifact_version",
        sa.Column("artifact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("file_id", sa.String(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["artifact_id"], ["chat_artifact.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["file_id"], ["file_record.file_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("artifact_id", "version"),
        sa.UniqueConstraint("file_id"),
    )


def downgrade() -> None:
    op.drop_table("chat_artifact_version")
    op.drop_table("chat_artifact")
